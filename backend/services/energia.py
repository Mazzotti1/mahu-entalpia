"""Gasto térmico do processo, em kW, e os fluxos de água que o acompanham.

    ṁ_ar_seco = V̇ / (3600 · v)     [kg de ar seco por segundo]
    Q_etapa   = ṁ_ar_seco · Δh      [kJ/s = kW]

O volume específico é o do ponto de ENTRADA (decisão A): é onde a vazão é medida. Usar o
do insuflamento daria ~0,4 % a mais em todos os números — pequeno, mas é uma escolha, e
fica registrada aqui em vez de virar acaso.

Nem toda etapa é serpentina. A umidificação adiabática troca calor com a água que evapora,
não com um fluido de processo: o custo dela é medido em kg/h de água, e somá-la ao kW de
aquecimento contaria uma energia que nenhuma caldeira forneceu.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.services.processo import Etapa, Processo
from backend.services.psicrometria import Estado, calcular_entalpia

# Calor específico da água líquida, kJ/(kg·K). Serve para a entalpia do condensado que
# deixa a serpentina, tomada na temperatura de saída do ar.
CP_AGUA = 4.186


@dataclass(frozen=True)
class CargaEtapa:
    etapa: Etapa
    # Positivo aquece o ar, negativo resfria.
    q_kw: float
    q_sensivel_kw: float
    q_latente_kw: float
    # Água evaporada no umidificador (positiva) e condensada nas serpentinas (positiva).
    agua_kg_h: float
    condensado_kg_h: float

    @property
    def tipo(self) -> str:
        return self.etapa.tipo


@dataclass(frozen=True)
class BalancoTermico:
    vazao_massica_kg_s: float
    cargas: list[CargaEtapa]
    q_aquecimento_kw: float
    q_refrigeracao_kw: float
    agua_umidificacao_kg_h: float
    condensado_kg_h: float


def vazao_massica_ar_seco(vazao_m3h: float, referencia: Estado) -> float:
    """kg de ar seco por segundo, a partir da vazão volumétrica em m³/h."""
    return vazao_m3h / 3600.0 / referencia.volume_especifico


def _carga_da_etapa(etapa: Etapa, vazao_kg_s: float) -> CargaEtapa:
    delta_w_kgkg = etapa.delta_w / 1000.0

    if not etapa.ativa:
        return CargaEtapa(etapa, 0.0, 0.0, 0.0, 0.0, 0.0)

    q_total = vazao_kg_s * etapa.delta_h

    # Sensível é a parcela que a mudança de temperatura sozinha explicaria, com a umidade
    # congelada na de entrada; o resto é latente. Definido assim a soma fecha exatamente,
    # o que a fórmula usual com cp médio não garante.
    h_so_temperatura = calcular_entalpia(etapa.fim.tbs, etapa.inicio.w)
    q_sensivel = vazao_kg_s * (h_so_temperatura - etapa.inicio.entalpia)
    q_latente = q_total - q_sensivel

    agua_kg_h = max(0.0, vazao_kg_s * delta_w_kgkg) * 3600.0
    condensado_kg_h = max(0.0, -vazao_kg_s * delta_w_kgkg) * 3600.0

    if condensado_kg_h > 0.0:
        # Balanço da serpentina com condensação:
        #     ṁ_ar·h_entra = ṁ_ar·h_sai + ṁ_água·h_água + Q_retirado
        # ou seja  Q_retirado = ṁ_ar·(h_entra − h_sai) − ṁ_água·h_água.
        #
        # Com `q_kw` na convenção "positivo aquece o ar", q_kw = −Q_retirado, então o termo
        # do condensado ENTRA SOMANDO e aproxima a carga de zero: parte da energia sai pelo
        # dreno e não é retirada pela água gelada. Vale ~0,2 % no caso de referência.
        # O condensado é tomado na temperatura de saída do ar, que deixa a serpentina saturado.
        entalpia_condensado = CP_AGUA * etapa.fim.tbs
        q_total += vazao_kg_s * (-delta_w_kgkg) * entalpia_condensado
        q_latente = q_total - q_sensivel

    return CargaEtapa(
        etapa=etapa,
        q_kw=q_total,
        q_sensivel_kw=q_sensivel,
        q_latente_kw=q_latente,
        agua_kg_h=agua_kg_h,
        condensado_kg_h=condensado_kg_h,
    )


def calcular_balanco(processo: Processo) -> BalancoTermico:
    """Distribui o gasto térmico entre as etapas e agrega os totais."""
    entrada = processo.pontos["P1"]
    vazao_kg_s = vazao_massica_ar_seco(processo.setpoints.vazao_m3h, entrada)

    cargas = [_carga_da_etapa(etapa, vazao_kg_s) for etapa in processo.etapas]

    # Só serpentina entra nos totais de kW. A umidificação adiabática fica de fora: o calor
    # dela vem do próprio ar, e aparece em `agua_umidificacao_kg_h`.
    aquecimento = sum(
        carga.q_kw for carga in cargas if carga.tipo == "aquecimento_sensivel"
    )
    refrigeracao = sum(
        -carga.q_kw
        for carga in cargas
        if carga.tipo in ("resfriamento_sensivel", "resfriamento_desumidificacao")
    )

    return BalancoTermico(
        vazao_massica_kg_s=vazao_kg_s,
        cargas=cargas,
        q_aquecimento_kw=aquecimento,
        q_refrigeracao_kw=refrigeracao,
        agua_umidificacao_kg_h=sum(carga.agua_kg_h for carga in cargas),
        condensado_kg_h=sum(carga.condensado_kg_h for carga in cargas),
    )
