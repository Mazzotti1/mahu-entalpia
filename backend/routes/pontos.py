from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from backend.database import get_db
from backend.models import (
    MahuCamposInput,
    MahuLeituraResponse,
    PontoInput,
    PontoResponse,
    SimulacaoInput,
    SimulacaoResponse,
)
from backend.services.mahu import construir_simulacao
from backend.services.mahu_ocr import ler_mahu
from backend.services.psicrometria import calcular_ponto

router = APIRouter(prefix="/api", tags=["psicrometria"])

# Foto de celular fica na casa de 5-10 MB; acima disso é abuso e não leitura de painel.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


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
    return await _persistir_simulacao(simulacao)


async def _persistir_simulacao(simulacao: SimulacaoInput) -> SimulacaoResponse:
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
            "INSERT INTO simulacoes (nome, descricao) VALUES (?, ?)",
            (simulacao.nome, simulacao.descricao),
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

    return SimulacaoResponse(id=simulacao_id, nome=simulacao.nome, pontos=pontos_final)


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

    return MahuLeituraResponse(**leitura)


@router.post("/mahu/simulacao", response_model=SimulacaoResponse)
async def criar_simulacao_mahu(campos: MahuCamposInput) -> SimulacaoResponse:
    """Monta e persiste a simulação a partir dos campos do MAHU já conferidos.

    Existe para que o frontend possa corrigir uma leitura de OCR sem ter de reproduzir o
    mapeamento campo -> ponto: quem traduz MAHU em P1..P4 continua sendo o backend.
    """
    return await _persistir_simulacao(construir_simulacao(campos))
