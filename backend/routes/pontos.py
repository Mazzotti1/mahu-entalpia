from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import AsyncIterator

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from backend.database import get_db
from backend.models import (
    MahuAviso,
    MahuCamposInput,
    MahuLeituraResponse,
    PontoInput,
    PontoResponse,
    SimulacaoInput,
    SimulacaoListaResponse,
    SimulacaoResponse,
    SimulacaoResumo,
)
from backend.services.eventos import difusor
from backend.services.mahu import construir_simulacao
from backend.services.mahu_campos import CAMPOS_OBRIGATORIOS
from backend.services.mahu_validacao import validar_leitura
from backend.services.psicrometria import calcular_ponto
from backend.services.telemetria_ocr import (
    registrar_aplicacao,
    registrar_leitura,
    ultima_leitura_aplicada,
)

router = APIRouter(prefix="/api", tags=["psicrometria"])

# Foto de celular fica na casa de 5-10 MB; acima disso é abuso e não leitura de painel.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# Intervalo do keepalive do SSE. Precisa ser menor que o proxy_read_timeout do nginx
# (300 s), senão uma conexão sem leituras é derrubada por ociosidade.
HEARTBEAT_SEGUNDOS = 25.0
# Teto do reenvio na reconexão: um cliente que ficou dias fora recarrega a lista inteira
# em vez de receber um jato de eventos.
MAX_CATCH_UP = 50


@router.post("/calcular", response_model=PontoResponse)
async def calcular_ponto_endpoint(ponto: PontoInput) -> PontoResponse:
    try:
        resultado = calcular_ponto(
            tbs=ponto.tbs,
            ur=ponto.ur,
            entalpia=ponto.entalpia,
            w_abs=ponto.w_abs,
            pressao_atm=ponto.pressao_atm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PontoResponse(label=ponto.label, **resultado)


@router.post("/simulacao", response_model=SimulacaoResponse)
async def criar_simulacao(simulacao: SimulacaoInput) -> SimulacaoResponse:
    return await persistir_simulacao(simulacao)


async def persistir_simulacao(
    simulacao: SimulacaoInput,
    *,
    origem: str = "manual",
    leitura_id: int | None = None,
) -> SimulacaoResponse:
    pontos_response: list[PontoResponse] = []

    try:
        for ponto in simulacao.pontos:
            calculado = calcular_ponto(
                tbs=ponto.tbs,
                ur=ponto.ur,
                entalpia=ponto.entalpia,
                w_abs=ponto.w_abs,
                pressao_atm=ponto.pressao_atm,
            )
            pontos_response.append(PontoResponse(label=ponto.label, **calculado))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO simulacoes (nome, descricao, origem, leitura_id) VALUES (?, ?, ?, ?)",
            (simulacao.nome, simulacao.descricao, origem, leitura_id),
        )
        simulacao_id = cursor.lastrowid
        for ordem, (ponto_input, ponto_calc) in enumerate(zip(simulacao.pontos, pontos_response), start=1):
            cursor_ponto = await db.execute(
                """
                INSERT INTO pontos_psicrometricos (
                    label, tbs, ur, entalpia, w_abs, pressao_atm,
                    w_calculado, h_calculado, ur_calculado, tbu_calculado,
                    volume_especifico, ponto_orvalho
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ponto_input.label,
                    ponto_input.tbs,
                    ponto_input.ur,
                    ponto_input.entalpia,
                    ponto_input.w_abs,
                    ponto_input.pressao_atm,
                    ponto_calc.w,
                    ponto_calc.entalpia,
                    ponto_calc.ur,
                    ponto_calc.tbu,
                    ponto_calc.volume_especifico,
                    ponto_calc.ponto_orvalho,
                ),
            )
            ponto_id = cursor_ponto.lastrowid
            await db.execute(
                "INSERT INTO simulacao_pontos (simulacao_id, ponto_id, ordem) VALUES (?, ?, ?)",
                (simulacao_id, ponto_id, ordem),
            )
        await db.commit()

    pontos_final = []
    async with get_db() as db:
        rows_query = await db.execute(
            """
            SELECT p.id, p.label, p.tbs, p.ur, p.entalpia, p.w_abs,
                   p.w_calculado, p.h_calculado, p.ur_calculado, p.tbu_calculado,
                   p.volume_especifico, p.ponto_orvalho
            FROM pontos_psicrometricos p
            JOIN simulacao_pontos sp ON sp.ponto_id = p.id
            WHERE sp.simulacao_id = ?
            ORDER BY sp.ordem
            """,
            (simulacao_id,),
        )
        rows = await rows_query.fetchall()
        for row in rows:
            pontos_final.append(
                PontoResponse(
                    id=row["id"],
                    label=row["label"],
                    tbs=row["tbs"],
                    w=row["w_calculado"],
                    ur=row["ur_calculado"],
                    entalpia=row["h_calculado"],
                    tbu=row["tbu_calculado"],
                    volume_especifico=row["volume_especifico"],
                    ponto_orvalho=row["ponto_orvalho"],
                    fonte_calculo=source_from_db_row(row),
                )
            )

    # Depois do commit: quem recebe o aviso vai consultar a linha, e ela precisa existir.
    difusor.publicar(simulacao_id)

    return SimulacaoResponse(id=simulacao_id, nome=simulacao.nome, pontos=pontos_final)


def _para_iso_utc(criado_em: str | None) -> str:
    """"2026-07-28 14:03:11" (CURRENT_TIMESTAMP do SQLite, em UTC) -> ISO 8601 com Z.

    Sem o sufixo o navegador trataria a string como hora local e a lista de histórico
    mostraria cada leitura deslocada pelo fuso.
    """
    if not criado_em:
        return ""
    return f"{criado_em.replace(' ', 'T')}Z"


_SELECT_RESUMO = """
    SELECT s.id, s.nome, s.criado_em,
           (SELECT COUNT(*) FROM simulacao_pontos sp WHERE sp.simulacao_id = s.id)
               AS total_pontos,
           p.tbs AS p1_tbs, p.ur_calculado AS p1_ur
    FROM simulacoes s
    LEFT JOIN simulacao_pontos sp1
           ON sp1.simulacao_id = s.id AND sp1.ordem = 1
    LEFT JOIN pontos_psicrometricos p ON p.id = sp1.ponto_id
"""


async def _consultar_resumos(sufixo_sql: str, parametros: tuple) -> list[SimulacaoResumo]:
    async with get_db() as db:
        cursor = await db.execute(_SELECT_RESUMO + sufixo_sql, parametros)
        rows = await cursor.fetchall()
    return [
        SimulacaoResumo(
            id=row["id"],
            nome=row["nome"],
            criado_em=_para_iso_utc(row["criado_em"]),
            total_pontos=row["total_pontos"],
            p1_tbs=row["p1_tbs"],
            p1_ur=row["p1_ur"],
        )
        for row in rows
    ]


@router.get("/simulacoes", response_model=SimulacaoListaResponse)
async def listar_simulacoes(
    limite: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> SimulacaoListaResponse:
    """Histórico das leituras, da mais recente para a mais antiga.

    `criado_em` tem resolução de segundo e duas leituras podem cair no mesmo instante,
    por isso o desempate por id — sem ele a paginação poderia repetir ou pular linhas.
    """
    async with get_db() as db:
        total_query = await db.execute("SELECT COUNT(*) AS total FROM simulacoes")
        total = (await total_query.fetchone())["total"]

    itens = await _consultar_resumos(
        "ORDER BY s.criado_em DESC, s.id DESC LIMIT ? OFFSET ?",
        (limite, offset),
    )
    return SimulacaoListaResponse(total=total, itens=itens)


def _evento_sse(resumo: SimulacaoResumo) -> str:
    """Um evento SSE. O `id:` é o que o navegador devolve como Last-Event-ID ao reconectar."""
    return f"id: {resumo.id}\nevent: simulacao\ndata: {resumo.model_dump_json()}\n\n"


@router.get("/simulacoes/stream")
async def stream_simulacoes(
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Empurra cada leitura nova assim que ela é gravada.

    Na reconexão o navegador manda de volta o id do último evento que recebeu, e o que
    ficou para trás é reenviado antes de o stream continuar — é o que cobre o celular
    trocando de rede ou a aba suspensa.
    """
    try:
        desde = int(last_event_id) if last_event_id else None
    except ValueError:
        desde = None

    async def gerar() -> AsyncIterator[str]:
        # A inscrição vem antes do catch-up: assim uma gravação que aconteça no meio do
        # reenvio fica na fila em vez de se perder na janela entre as duas etapas.
        async with difusor.inscrever() as fila:
            if desde is not None:
                for resumo in await _consultar_resumos(
                    "WHERE s.id > ? ORDER BY s.id ASC LIMIT ?", (desde, MAX_CATCH_UP)
                ):
                    yield _evento_sse(resumo)

            while True:
                try:
                    simulacao_id = await asyncio.wait_for(fila.get(), timeout=HEARTBEAT_SEGUNDOS)
                except asyncio.TimeoutError:
                    # Comentário SSE: mantém a conexão viva através de proxies que derrubam
                    # conexões ociosas, e é ignorado pelo EventSource.
                    yield ": keepalive\n\n"
                    continue

                resumos = await _consultar_resumos("WHERE s.id = ?", (simulacao_id,))
                if resumos:
                    yield _evento_sse(resumos[0])

    return StreamingResponse(
        gerar(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # O nginx respeita este cabeçalho e desliga o buffer só para esta resposta.
            # Sem isso ele segura os eventos e o stream chega em blocos, anulando o ganho.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/simulacao/{simulacao_id}", response_model=SimulacaoResponse)
async def get_simulacao(simulacao_id: int) -> SimulacaoResponse:
    async with get_db() as db:
        sim_query = await db.execute(
            "SELECT id, nome FROM simulacoes WHERE id = ?",
            (simulacao_id,),
        )
        sim = await sim_query.fetchone()
        if not sim:
            raise HTTPException(status_code=404, detail="Simulação não encontrada.")

        points_query = await db.execute(
            """
            SELECT p.id, p.label, p.tbs, p.ur, p.entalpia, p.w_abs,
                   p.w_calculado, p.h_calculado, p.ur_calculado, p.tbu_calculado,
                   p.volume_especifico, p.ponto_orvalho
            FROM pontos_psicrometricos p
            JOIN simulacao_pontos sp ON sp.ponto_id = p.id
            WHERE sp.simulacao_id = ?
            ORDER BY sp.ordem
            """,
            (simulacao_id,),
        )
        points_rows = await points_query.fetchall()

    pontos = [
        PontoResponse(
            id=row["id"],
            label=row["label"],
            tbs=row["tbs"],
            w=row["w_calculado"],
            ur=row["ur_calculado"],
            entalpia=row["h_calculado"],
            tbu=row["tbu_calculado"],
            volume_especifico=row["volume_especifico"],
            ponto_orvalho=row["ponto_orvalho"],
            fonte_calculo=source_from_db_row(row),
        )
        for row in points_rows
    ]
    return SimulacaoResponse(id=sim["id"], nome=sim["nome"], pontos=pontos)


def source_from_db_row(row) -> str:
    if row["w_abs"] is not None:
        return "w_abs"
    if row["ur"] is not None:
        return "ur"
    if row["entalpia"] is not None:
        return "entalpia"
    return "banco"


@router.post("/mahu/ler", response_model=MahuLeituraResponse)
async def ler_mahu_endpoint(image: UploadFile = File(...)) -> MahuLeituraResponse:
    if image.content_type is None or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Envie um arquivo de imagem válido.")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="A imagem enviada está vazia.")
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Imagem acima do limite de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    try:
        # Import tardio, como o do easyocr em mahu_ocr.py e pelo mesmo motivo: o módulo
        # carrega OpenCV. No topo do arquivo, uma instalação sem cv2 derrubaria a API
        # inteira no import — e o 503 abaixo, que existe justamente para esse caso, nunca
        # chegaria a rodar.
        from backend.services.mahu_ocr import ler_mahu

        # O OCR é síncrono e gasta segundos de CPU: rodando direto aqui ele travaria o
        # event loop e a API pararia de responder durante a leitura.
        leitura = await run_in_threadpool(ler_mahu, image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Motor de OCR indisponível. Instale as dependências de backend/requirements.txt.",
        ) from exc

    campos = leitura["campos"]
    avisos = validar_leitura(leitura["valores"], anterior=await ultima_leitura_aplicada())

    # Confiança por campo não é suficiente: a leitura que corrompeu quatro campos de uma vez
    # em produção passou com todos eles marcados "ok". Um aviso cruzado manda para
    # conferência mesmo quando cada campo, isolado, parecia bom.
    requires_review = (
        any(campo.obrigatorio and campo.status != "ok" for campo in campos) or bool(avisos)
    )

    leitura_id = await registrar_leitura(
        campos, requires_review=requires_review, avisos=avisos, image_bytes=image_bytes
    )

    return MahuLeituraResponse(
        id=leitura_id,
        campos=campos,
        missing_keys=leitura["missing_keys"],
        requires_review=requires_review,
        avisos=[MahuAviso(**asdict(aviso)) for aviso in avisos],
    )


@router.post("/mahu/simulacao", response_model=SimulacaoResponse)
async def criar_simulacao_mahu(campos: MahuCamposInput) -> SimulacaoResponse:
    """Monta e persiste a simulação a partir dos campos do MAHU já conferidos.

    Existe para que o frontend possa corrigir uma leitura de OCR sem ter de reproduzir o
    mapeamento campo -> ponto: quem traduz MAHU em P1..P4 continua sendo o backend.

    Com `leitura_id`, o que foi aplicado é confrontado com o que tinha sido sugerido — é
    daí que sai o rótulo de erro de OCR que o avaliador consome.
    """
    origem = "manual"
    if campos.leitura_id is not None:
        aplicados = {key: getattr(campos, key) for key in CAMPOS_OBRIGATORIOS}
        origem = await registrar_aplicacao(campos.leitura_id, aplicados)

    return await persistir_simulacao(
        construir_simulacao(campos), origem=origem, leitura_id=campos.leitura_id
    )
