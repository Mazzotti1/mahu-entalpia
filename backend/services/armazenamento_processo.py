"""Leitura e gravação do processo e dos setpoints.

Os setpoints são uma linha só, compartilhada: a planta tem uma configuração, e quem abrir
o app do celular precisa ver a mesma que está valendo. Já os setpoints *usados* em cada
processo são copiados junto com ele — sem essa cópia, mudar a configuração reescreveria o
significado de todo o histórico.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from backend.database import get_db
from backend.models import (
    DesvioResponse,
    EtapaResponse,
    GastoTermicoHistoricoItem,
    PontoProcessoResponse,
    ProcessoAviso,
    ProcessoResponse,
    SetpointsInput,
    TotaisProcessoResponse,
)
from backend.services.desvios import Desvio
from backend.services.energia import BalancoTermico
from backend.services.processo import Processo, Setpoints
from backend.services.psicrometria import Estado

_CAMPOS_SETPOINTS = ("w_saida", "tbs_final", "entalpia_alvo", "vazao_m3h", "pressao_atm")

# `entalpia_alvo_seco` só existe na tabela `setpoints` (configuração vigente da planta).
# `processos` guarda a cópia usada em cada execução (`_CAMPOS_SETPOINTS` acima) e nunca
# recebeu essa coluna: a carta otimizada não persiste corrida nenhuma ali, então não há
# histórico dela para reconstruir.
_CAMPOS_SETPOINTS_CONFIG = _CAMPOS_SETPOINTS + ("entalpia_alvo_seco",)

# Só P1 vem direto do painel (TT01+MT_01); P2..P5 são a cadeia calculada dos setpoints
# (decisão B). Ver o comentário de `PontoProcessoResponse.fonte`.
_FONTE_POR_LABEL = {"P1": "lido_digitado"}


def para_dominio(setpoints: SetpointsInput) -> Setpoints:
    return Setpoints(**setpoints.model_dump())


def ponto_para_response(
    label: str, estado: Estado, *, fonte: str | None = None
) -> PontoProcessoResponse:
    """`fonte` forçada é para a cadeia MEDIDA, onde todo ponto veio de instrumento.

    Sem ela, `_FONTE_POR_LABEL` marcaria de "calculado" os pontos da Carta Atual — que são
    exatamente o contrário disso — porque os rótulos de lá são nomes de campo (TT_04, TT_06)
    e não os P1..P5 da cadeia dos setpoints.
    """
    return PontoProcessoResponse(
        label=label,
        tbs=round(estado.tbs, 2),
        w=round(estado.w, 3),
        ur=round(estado.ur, 2),
        entalpia=round(estado.entalpia, 2),
        tbu=round(estado.tbu, 2),
        volume_especifico=round(estado.volume_especifico, 4),
        ponto_orvalho=round(estado.ponto_orvalho, 2),
        saturado=estado.saturado,
        fonte=fonte or _FONTE_POR_LABEL.get(label, "calculado"),
    )


def montar_response(
    processo: Processo,
    balanco: BalancoTermico,
    *,
    processo_id: int | None = None,
    simulacao_id: int | None = None,
    desvios: list[Desvio] | None = None,
    delta_h_entalpia: float | None = None,
    regiao: int | None = None,
    medido: ProcessoResponse | None = None,
    fonte_dos_pontos: str | None = None,
) -> ProcessoResponse:
    etapas = [
        EtapaResponse(
            tipo=carga.tipo,
            de=carga.etapa.de,
            para=carga.etapa.para,
            ativa=carga.etapa.ativa,
            delta_h=round(carga.etapa.delta_h, 3),
            delta_w=round(carga.etapa.delta_w, 3),
            q_kw=round(carga.q_kw, 2),
            q_sensivel_kw=round(carga.q_sensivel_kw, 2),
            q_latente_kw=round(carga.q_latente_kw, 2),
            agua_kg_h=round(carga.agua_kg_h, 2),
            condensado_kg_h=round(carga.condensado_kg_h, 2),
            joelho=(
                ponto_para_response("joelho", carga.etapa.joelho)
                if carga.etapa.joelho is not None
                else None
            ),
        )
        for carga in balanco.cargas
    ]

    return ProcessoResponse(
        id=processo_id,
        simulacao_id=simulacao_id,
        setpoints=SetpointsInput(**asdict(processo.setpoints)),
        pontos=[
            ponto_para_response(label, processo.pontos[label], fonte=fonte_dos_pontos)
            for label in processo.ordem
        ],
        etapas=etapas,
        totais=TotaisProcessoResponse(
            vazao_massica_kg_s=round(balanco.vazao_massica_kg_s, 4),
            q_aquecimento_kw=round(balanco.q_aquecimento_kw, 2),
            q_refrigeracao_kw=round(balanco.q_refrigeracao_kw, 2),
            agua_umidificacao_kg_h=round(balanco.agua_umidificacao_kg_h, 2),
            condensado_kg_h=round(balanco.condensado_kg_h, 2),
        ),
        avisos=[ProcessoAviso(codigo=a.codigo, mensagem=a.mensagem) for a in processo.avisos],
        desvios=[
            DesvioResponse(
                campo=d.campo,
                ponto=d.ponto,
                propriedade=d.propriedade,
                unidade=d.unidade,
                medido=round(d.medido, 2),
                calculado=round(d.calculado, 2),
                diferenca=round(d.diferenca, 2),
            )
            for d in (desvios or [])
        ],
        delta_h_entalpia=round(delta_h_entalpia, 2) if delta_h_entalpia is not None else None,
        regiao=regiao,
        medido=medido,
    )


async def ler_setpoints() -> SetpointsInput:
    async with get_db() as db:
        cursor = await db.execute(
            f"SELECT {', '.join(_CAMPOS_SETPOINTS_CONFIG)} FROM setpoints WHERE id = 1"
        )
        linha = await cursor.fetchone()
    # A migração 3 semeia a linha; ausente, os defaults do modelo valem.
    return SetpointsInput() if linha is None else SetpointsInput(**dict(linha))


async def gravar_setpoints(setpoints: SetpointsInput) -> SetpointsInput:
    # Colunas do INSERT e o SET do UPDATE derivam da MESMA tupla que gera os valores: uma
    # lista de colunas escrita à mão ao lado de outra, em ordem diferente, é como coluna e
    # valor saem trocados sem o menor aviso (SQLite liga por posição, não por nome).
    colunas = ", ".join(_CAMPOS_SETPOINTS_CONFIG)
    placeholders = ", ".join("?" for _ in _CAMPOS_SETPOINTS_CONFIG)
    atualiza = ", ".join(f"{campo} = excluded.{campo}" for campo in _CAMPOS_SETPOINTS_CONFIG)
    async with get_db() as db:
        await db.execute(
            f"""
            INSERT INTO setpoints (id, {colunas})
            VALUES (1, {placeholders})
            ON CONFLICT(id) DO UPDATE SET {atualiza}, atualizado_em = CURRENT_TIMESTAMP
            """,
            tuple(getattr(setpoints, campo) for campo in _CAMPOS_SETPOINTS_CONFIG),
        )
        await db.commit()
    return setpoints


_CAMPOS_TOTAIS = (
    "vazao_massica_kg_s",
    "q_aquecimento_kw",
    "q_refrigeracao_kw",
    "agua_umidificacao_kg_h",
    "condensado_kg_h",
)


async def ler_processo_por_simulacao(simulacao_id: int) -> ProcessoResponse | None:
    """Reconstrói um processo gravado, para o histórico não perder as etapas e o kW.

    Os pontos vêm de `pontos_psicrometricos` (onde o histórico já os lê) e as etapas de
    `etapas_processo`. Recalcular a partir da entrada daria outro resultado assim que os
    setpoints mudassem — por isso a leitura é do que foi gravado, não uma nova resolução.
    """
    async with get_db() as db:
        cursor = await db.execute(
            f"""
            SELECT id, {", ".join(_CAMPOS_SETPOINTS)}, {", ".join(_CAMPOS_TOTAIS)}, avisos,
                   delta_h_entalpia
            FROM processos WHERE simulacao_id = ? ORDER BY id DESC LIMIT 1
            """,
            (simulacao_id,),
        )
        cabecalho = await cursor.fetchone()
        if cabecalho is None:
            return None

        cursor = await db.execute(
            """
            SELECT p.label, p.tbs, p.w_calculado, p.ur_calculado, p.h_calculado,
                   p.tbu_calculado, p.volume_especifico, p.ponto_orvalho
            FROM pontos_psicrometricos p
            JOIN simulacao_pontos sp ON sp.ponto_id = p.id
            WHERE sp.simulacao_id = ?
            ORDER BY sp.ordem
            """,
            (simulacao_id,),
        )
        pontos = await cursor.fetchall()

        cursor = await db.execute(
            "SELECT * FROM etapas_processo WHERE processo_id = ? ORDER BY ordem",
            (cabecalho["id"],),
        )
        etapas = await cursor.fetchall()

        cursor = await db.execute(
            """
            SELECT campo, ponto, propriedade, unidade, medido, calculado, diferenca
            FROM desvios_processo WHERE processo_id = ?
            """,
            (cabecalho["id"],),
        )
        desvios = await cursor.fetchall()

    return ProcessoResponse(
        id=cabecalho["id"],
        simulacao_id=simulacao_id,
        setpoints=SetpointsInput(**{campo: cabecalho[campo] for campo in _CAMPOS_SETPOINTS}),
        pontos=[
            PontoProcessoResponse(
                label=linha["label"],
                tbs=linha["tbs"],
                w=linha["w_calculado"],
                ur=linha["ur_calculado"],
                entalpia=linha["h_calculado"],
                tbu=linha["tbu_calculado"],
                volume_especifico=linha["volume_especifico"],
                ponto_orvalho=linha["ponto_orvalho"],
                # Saturado é o que está em cima da curva; a folga cobre o arredondamento
                # de duas casas com que os valores foram gravados.
                saturado=linha["ur_calculado"] >= 99.5,
                fonte=_FONTE_POR_LABEL.get(linha["label"], "calculado"),
            )
            for linha in pontos
        ],
        etapas=[
            EtapaResponse(
                tipo=linha["tipo"],
                de=linha["de"],
                para=linha["para"],
                ativa=linha["tipo"] != "nula",
                delta_h=round(linha["delta_h"], 3),
                delta_w=round(linha["delta_w"], 3),
                q_kw=round(linha["q_kw"], 2),
                q_sensivel_kw=round(linha["q_sensivel_kw"], 2),
                q_latente_kw=round(linha["q_latente_kw"], 2),
                agua_kg_h=round(linha["agua_kg_h"], 2),
                condensado_kg_h=round(linha["condensado_kg_h"], 2),
                joelho=(
                    ponto_para_response(
                        "joelho",
                        Estado(
                            tbs=linha["joelho_tbs"],
                            w=linha["joelho_w"],
                            pressao_atm=cabecalho["pressao_atm"],
                        ),
                    )
                    if linha["joelho_tbs"] is not None
                    else None
                ),
            )
            for linha in etapas
        ],
        totais=TotaisProcessoResponse(
            **{campo: round(cabecalho[campo], 4) for campo in _CAMPOS_TOTAIS}
        ),
        avisos=[ProcessoAviso(**a) for a in json.loads(cabecalho["avisos"] or "[]")],
        desvios=[
            DesvioResponse(
                campo=linha["campo"],
                ponto=linha["ponto"],
                propriedade=linha["propriedade"],
                unidade=linha["unidade"],
                medido=linha["medido"],
                calculado=linha["calculado"],
                diferenca=linha["diferenca"],
            )
            for linha in desvios
        ],
        delta_h_entalpia=cabecalho["delta_h_entalpia"],
    )


async def gravar_processo(
    simulacao_id: int,
    processo: Processo,
    balanco: BalancoTermico,
    *,
    desvios: list[Desvio] | None = None,
    delta_h_entalpia: float | None = None,
) -> int:
    """Grava o processo, suas etapas e os desvios do painel, e devolve o id."""
    setpoints = processo.setpoints
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO processos (
                simulacao_id, w_saida, tbs_final, entalpia_alvo, vazao_m3h, pressao_atm,
                vazao_massica_kg_s, q_aquecimento_kw, q_refrigeracao_kw,
                agua_umidificacao_kg_h, condensado_kg_h, avisos, delta_h_entalpia
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                simulacao_id,
                setpoints.w_saida,
                setpoints.tbs_final,
                setpoints.entalpia_alvo,
                setpoints.vazao_m3h,
                setpoints.pressao_atm,
                balanco.vazao_massica_kg_s,
                balanco.q_aquecimento_kw,
                balanco.q_refrigeracao_kw,
                balanco.agua_umidificacao_kg_h,
                balanco.condensado_kg_h,
                json.dumps([asdict(a) for a in processo.avisos], ensure_ascii=False),
                delta_h_entalpia,
            ),
        )
        processo_id = cursor.lastrowid

        if desvios:
            await db.executemany(
                """
                INSERT INTO desvios_processo (
                    processo_id, campo, ponto, propriedade, unidade, medido, calculado, diferenca
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        processo_id,
                        d.campo,
                        d.ponto,
                        d.propriedade,
                        d.unidade,
                        d.medido,
                        d.calculado,
                        d.diferenca,
                    )
                    for d in desvios
                ],
            )

        await db.executemany(
            """
            INSERT INTO etapas_processo (
                processo_id, ordem, tipo, de, para, delta_h, delta_w,
                q_kw, q_sensivel_kw, q_latente_kw, agua_kg_h, condensado_kg_h,
                joelho_tbs, joelho_w
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    processo_id,
                    ordem,
                    carga.tipo,
                    carga.etapa.de,
                    carga.etapa.para,
                    carga.etapa.delta_h,
                    carga.etapa.delta_w,
                    carga.q_kw,
                    carga.q_sensivel_kw,
                    carga.q_latente_kw,
                    carga.agua_kg_h,
                    carga.condensado_kg_h,
                    carga.etapa.joelho.tbs if carga.etapa.joelho else None,
                    carga.etapa.joelho.w if carga.etapa.joelho else None,
                )
                for ordem, carga in enumerate(balanco.cargas, start=1)
            ],
        )
        await db.commit()

    return processo_id


async def listar_historico_gasto_termico(limite: int = 200) -> list[GastoTermicoHistoricoItem]:
    """Uma linha por leitura: gasto térmico total e Delta H, para o gráfico e a planilha.

    Não filtra por `delta_h_entalpia` nulo aqui: leituras sem o PID TT04 ENTALPIA (PV)
    informado ainda têm gasto térmico e devem aparecer na planilha. Quem consome (gráfico)
    é quem decide ignorar as linhas sem Delta H.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, simulacao_id, criado_em, q_aquecimento_kw, q_refrigeracao_kw,
                   delta_h_entalpia
            FROM processos
            ORDER BY criado_em DESC, id DESC
            LIMIT ?
            """,
            (limite,),
        )
        linhas = await cursor.fetchall()

    return [
        GastoTermicoHistoricoItem(
            processo_id=linha["id"],
            simulacao_id=linha["simulacao_id"],
            criado_em=f"{linha['criado_em']}Z",
            q_aquecimento_kw=linha["q_aquecimento_kw"],
            q_refrigeracao_kw=linha["q_refrigeracao_kw"],
            gasto_termico_kw=linha["q_aquecimento_kw"] + linha["q_refrigeracao_kw"],
            delta_h_entalpia=linha["delta_h_entalpia"],
        )
        for linha in linhas
    ]

    return processo_id
