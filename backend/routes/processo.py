"""Endpoints do processo completo: 5 pontos, etapas e gasto térmico.

Separado de `pontos.py` porque são coisas diferentes: lá é o CRUD de pontos isolados que o
histórico e o SSE já usam; aqui é o processo encadeado, que precisa dos setpoints.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException

from backend.models import (
    GastoTermicoHistoricoResponse,
    MahuCamposInput,
    ProcessoInput,
    ProcessoOtimizadoInput,
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
from backend.services.processo import (
    Processo,
    Setpoints,
    classificar_regiao,
    resolver_processo,
    resolver_processo_otimizado,
)
from backend.services.processo_medido import resolver_processo_medido
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


@router.post("/processo/otimizado", response_model=ProcessoResponse)
async def calcular_processo_otimizado(
    entrada: ProcessoOtimizadoInput, usuario: Usuario = Depends(usuario_atual)
) -> ProcessoResponse:
    """A carta otimizada para o mesmo P1: escolhe o alvo de entalpia por região e resolve a
    mesma cadeia de sempre (ver `resolver_processo_otimizado`).

    Não persiste: é um comparativo hipotético para a carta, não uma leitura operacional —
    salvá-lo junto do histórico misturaria os dois no gráfico de gasto térmico.
    """
    setpoints = await ler_setpoints()
    dominio = para_dominio(setpoints)

    p1 = estado_por_ur(entrada.tbs, entrada.ur, dominio.pressao_atm)
    if entrada.entalpia_alvo is None:
        processo = resolver_processo_otimizado(p1, dominio)
    else:
        # PID TT04 ENTALPIA (SP) digitado: o alvo passa a ser o que o usuário informou, em vez
        # do escolhido por região. `w_saida`/`tbs_final` continuam vindo da rota otimizada —
        # o campo digitado é UM setpoint, não a configuração inteira da carta.
        processo = resolver_processo_otimizado(
            p1, replace(dominio, entalpia_alvo=entrada.entalpia_alvo, entalpia_alvo_seco=entrada.entalpia_alvo)
        )

    balanco = calcular_balanco(processo)

    return montar_response(processo, balanco, regiao=classificar_regiao(p1))


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


def _montar_carta_atual(
    medidos: dict[str, float], dominio: Setpoints
) -> ProcessoResponse | None:
    """A cadeia medida do painel, já com o gasto térmico dela. `None` sem ar de entrada.

    Os pontos vão marcados como `lido_digitado` em bloco: nesta carta nenhum deles foi
    calculado a partir de setpoint, que é a diferença inteira entre as duas cartas.
    """
    processo = resolver_processo_medido(medidos, dominio)
    if processo is None:
        return None
    return montar_response(
        processo, calcular_balanco(processo), fonte_dos_pontos="lido_digitado"
    )


@router.post("/mahu/processo", response_model=ProcessoResponse)
async def calcular_processo_do_mahu(
    campos: MahuCamposInput, usuario: Usuario = Depends(usuario_atual)
) -> ProcessoResponse:
    """Resolve as DUAS cadeias da mesma leitura do painel já conferida.

    A **Carta Calculada** (resposta principal) sai dos setpoints: só TT01 e MT_01 a
    alimentam, porque são o ar de entrada, e os demais campos viram `desvios` — decisões B
    e D. É o processo que a planta deveria estar fazendo.

    A **Carta Atual** (`medido`) sai só do painel: cada ponto é posicionado pelos
    instrumentos daquele trecho do MAHU, sem nenhum setpoint no meio. É o processo que a
    planta está de fato fazendo, e é o que dá sentido a comparar o gasto térmico dos dois.

    Só a calculada é persistida. A medida é derivada inteiramente dos campos gravados na
    leitura, então guardá-la de novo seria duplicar o mesmo dado em duas tabelas.
    """
    setpoints = await ler_setpoints()
    dominio = para_dominio(setpoints)

    # PID TT04 ENTALPIA (SP) digitado manda no alvo desta execução, sem regravar a
    # configuração da planta — é a digitação individual do campo.
    if campos.tt04_entalpia_sp is not None:
        dominio = replace(dominio, entalpia_alvo=campos.tt04_entalpia_sp)

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

    medido = _montar_carta_atual(medidos, dominio)

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
        medido=medido,
    )


@router.get("/mahu/historico/gasto-termico", response_model=GastoTermicoHistoricoResponse)
async def obter_historico_gasto_termico(limite: int = 200) -> GastoTermicoHistoricoResponse:
    """Gasto térmico e Delta H de cada leitura, para o gráfico e a exportação em planilha."""
    return GastoTermicoHistoricoResponse(itens=await listar_historico_gasto_termico(limite))
