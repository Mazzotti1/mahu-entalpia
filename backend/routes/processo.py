"""Endpoints do processo completo: 5 pontos, etapas e gasto térmico.

Separado de `pontos.py` porque são coisas diferentes: lá é o CRUD de pontos isolados que o
histórico e o SSE já usam; aqui é o processo encadeado, que precisa dos setpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.models import (
    GastoTermicoHistoricoResponse,
    MahuCamposInput,
    ProcessoInput,
    ProcessoResponse,
    SetpointsInput,
    SimulacaoInput,
)
from backend.routes.pontos import persistir_simulacao
from backend.services.autenticacao import Usuario
from backend.services.desvios import Desvio, calcular_desvios
from backend.services.guardas import usuario_atual
from backend.services.mahu_campos import CAMPOS_CONFERIVEIS
from backend.services.telemetria_ocr import registrar_aplicacao
from backend.services.armazenamento_processo import (
    gravar_processo,
    gravar_setpoints,
    ler_processo_por_simulacao,
    ler_setpoints,
    listar_historico_gasto_termico,
    montar_response,
    para_dominio,
)
from backend.services.energia import calcular_balanco
from backend.services.processo import Processo, resolver_processo
from backend.services.psicrometria import estado_por_ur

router = APIRouter(prefix="/api", tags=["processo"])


@router.get("/setpoints", response_model=SetpointsInput)
async def obter_setpoints() -> SetpointsInput:
    return await ler_setpoints()


@router.put("/setpoints", response_model=SetpointsInput)
async def atualizar_setpoints(setpoints: SetpointsInput) -> SetpointsInput:
    return await gravar_setpoints(setpoints)


def _simulacao_do_processo(processo: Processo, nome: str, descricao: str | None) -> SimulacaoInput:
    """Os 5 pontos no formato que o histórico e a carta já consomem.

    Cada ponto vai com `w_abs`, e não com UR: é a única entrada que descreve o estado sem
    passar por uma inversão que poderia devolver 100,3 % num ponto saturado e ser recusada.
    """
    return SimulacaoInput(
        nome=nome,
        descricao=descricao,
        pontos=[
            {
                "label": label,
                "tbs": processo.pontos[label].tbs,
                "w_abs": processo.pontos[label].w,
                "pressao_atm": processo.setpoints.pressao_atm,
            }
            for label in processo.ordem
        ],
    )


@router.post("/processo", response_model=ProcessoResponse)
async def calcular_processo(
    entrada: ProcessoInput, usuario: Usuario = Depends(usuario_atual)
) -> ProcessoResponse:
    """Resolve o processo a partir do ar de entrada e persiste o resultado.

    Sem `setpoints` no corpo, usa os que estão gravados — é o caminho normal, já que a
    configuração é da planta e não da requisição.
    """
    setpoints = entrada.setpoints or await ler_setpoints()
    dominio = para_dominio(setpoints)

    processo = resolver_processo(
        estado_por_ur(entrada.tbs, entrada.ur, dominio.pressao_atm), dominio
    )
    balanco = calcular_balanco(processo)

    simulacao = await persistir_simulacao(
        _simulacao_do_processo(processo, entrada.nome, entrada.descricao),
        origem="processo",
        usuario_id=usuario.id,
    )
    processo_id = await gravar_processo(simulacao.id, processo, balanco)

    return montar_response(
        processo, balanco, processo_id=processo_id, simulacao_id=simulacao.id
    )


@router.get("/simulacao/{simulacao_id}/processo", response_model=ProcessoResponse)
async def obter_processo(simulacao_id: int) -> ProcessoResponse:
    """O processo gravado de uma simulação. 404 nas simulações anteriores à migração 3."""
    processo = await ler_processo_por_simulacao(simulacao_id)
    if processo is None:
        raise HTTPException(
            status_code=404, detail="Esta simulação não tem processo calculado."
        )
    return processo


def _delta_h_entalpia(desvios: list[Desvio]) -> float | None:
    """Entalpia do setpoint de P2 menos a lida/digitada no PID TT04 ENTALPIA (PV).

    `Desvio.diferenca` é `medido - calculado`; Delta H é o oposto disso (setpoint menos
    capturado), então o sinal inverte.
    """
    return next(
        (-d.diferenca for d in desvios if d.campo == "tt04_entalpia_pv"),
        None,
    )


@router.post("/mahu/processo", response_model=ProcessoResponse)
async def calcular_processo_do_mahu(
    campos: MahuCamposInput, usuario: Usuario = Depends(usuario_atual)
) -> ProcessoResponse:
    """Resolve o processo a partir da leitura do painel já conferida.

    Só TT01 e MT_01 alimentam o cálculo: são o ar de entrada. TT_04, TT_06, TT07 e MT07
    passam a ser conferência — o processo em si vem dos setpoints (decisões B e D) — e
    voltam como `desvios`, que é o que diz se a planta está cumprindo o controle.
    """
    setpoints = await ler_setpoints()
    dominio = para_dominio(setpoints)

    processo = resolver_processo(
        estado_por_ur(campos.tt01, campos.mt_01, dominio.pressao_atm), dominio
    )
    balanco = calcular_balanco(processo)

    medidos = {
        key: valor
        for key in CAMPOS_CONFERIVEIS
        if (valor := getattr(campos, key, None)) is not None
    }
    desvios = calcular_desvios(processo, medidos)
    delta_h_entalpia = _delta_h_entalpia(desvios)

    origem = "manual"
    if campos.leitura_id is not None:
        # Os campos do bloco SP/PV/MV podem vir nulos: o painel os mostra com 17 px entre
        # linhas e nem toda foto os resolve. Filtrar aqui é o que permite eles entrarem no
        # corpus quando existem sem estragar o par sugerido/aplicado quando não existem.
        aplicados = medidos
        origem = await registrar_aplicacao(
            campos.leitura_id, aplicados, ms_na_conferencia=campos.ms_na_conferencia
        )

    simulacao = await persistir_simulacao(
        _simulacao_do_processo(processo, "Processo MAHU via OCR", "Leitura do monitor MAHU."),
        origem=origem,
        leitura_id=campos.leitura_id,
        usuario_id=usuario.id,
    )
    processo_id = await gravar_processo(
        simulacao.id, processo, balanco, desvios=desvios, delta_h_entalpia=delta_h_entalpia
    )

    return montar_response(
        processo,
        balanco,
        processo_id=processo_id,
        simulacao_id=simulacao.id,
        desvios=desvios,
        delta_h_entalpia=delta_h_entalpia,
    )


@router.get("/mahu/historico/gasto-termico", response_model=GastoTermicoHistoricoResponse)
async def obter_historico_gasto_termico(limite: int = 200) -> GastoTermicoHistoricoResponse:
    """Gasto térmico e Delta H de cada leitura, para o gráfico e a exportação em planilha."""
    return GastoTermicoHistoricoResponse(itens=await listar_historico_gasto_termico(limite))
