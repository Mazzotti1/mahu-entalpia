"""O gasto térmico convertido em dinheiro.

Existe porque kW não se somam. Um kW retirado pela serpentina fria e um kW entregue pela
serpentina quente aparecem com o mesmo número em `energia.py` e custam valores diferentes:
o frio passa pelo COP do chiller (3,5 kW de calor removido por kW elétrico consumido), o
calor pelo rendimento do aquecimento. Somar os dois em kW e chamar de "gasto" trata como
iguais duas coisas que a conta de luz cobra diferente.

    elétrico_frio   = Q_refrigeração / COP
    elétrico_quente = Q_aquecimento  / rendimento
    R$/h            = (elétrico_frio + elétrico_quente) · preço_kWh + água · preço_água

É esta a grandeza que o otimizador minimiza, e é nela que a comparação entre a Carta Atual
e a Carta Otimizada faz sentido para quem paga a conta.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.services.energia import BalancoTermico

# Densidade da água em kg/m³, para converter os kg/h do umidificador em volume tarifado.
_DENSIDADE_AGUA = 1000.0

# Horas num dia e num mês comercial de 30 dias. O custo por hora é o que a física dá; o
# mensal é o que faz alguém decidir mexer na planta.
HORAS_POR_DIA = 24.0
DIAS_POR_MES = 30.0


@dataclass(frozen=True)
class Tarifas:
    """Quanto custa cada insumo. Configuração da planta, não da requisição."""

    preco_kwh: float = 0.75
    # Coeficiente de performance do chiller: kW térmicos removidos por kW elétrico.
    cop_refrigeracao: float = 3.5
    # Rendimento do aquecimento, 0..1. Resistência elétrica fica perto de 1; caldeira, não.
    rendimento_aquecimento: float = 0.95
    preco_agua_m3: float = 12.0


@dataclass(frozen=True)
class Custo:
    """O que a cadeia custa por hora, aberto por origem."""

    energia_refrigeracao_kw: float
    energia_aquecimento_kw: float
    energia_total_kw: float
    reais_por_hora: float
    reais_por_dia: float
    reais_por_mes: float


def calcular_custo_de_totais(
    q_refrigeracao_kw: float,
    q_aquecimento_kw: float,
    agua_umidificacao_kg_h: float,
    tarifas: Tarifas,
) -> Custo:
    """A conta a partir dos três totais, sem exigir o balanço inteiro.

    Existe porque nem todo processo chega aqui com um `BalancoTermico` na mão: os do
    histórico voltam do banco já agregados. Reresolver a cadeia só para saber quanto ela
    custa daria outro resultado assim que os setpoints mudassem — e o histórico deixaria de
    descrever o que de fato rodou.

    A umidificação adiabática não entra no elétrico de propósito — o calor dela vem do
    próprio ar e nenhuma máquina o forneceu (ver `energia.py`) — mas a água entra no
    dinheiro, porque ela é comprada.
    """
    # Divisões protegidas: um COP ou rendimento zerado vindo de configuração errada não pode
    # derrubar a resposta inteira; sem o divisor, o kW térmico vale por si.
    cop = tarifas.cop_refrigeracao if tarifas.cop_refrigeracao > 0 else 1.0
    rendimento = tarifas.rendimento_aquecimento if tarifas.rendimento_aquecimento > 0 else 1.0

    eletrico_frio = q_refrigeracao_kw / cop
    eletrico_quente = q_aquecimento_kw / rendimento
    eletrico_total = eletrico_frio + eletrico_quente

    custo_agua = agua_umidificacao_kg_h / _DENSIDADE_AGUA * tarifas.preco_agua_m3
    reais_por_hora = eletrico_total * tarifas.preco_kwh + custo_agua

    return Custo(
        energia_refrigeracao_kw=eletrico_frio,
        energia_aquecimento_kw=eletrico_quente,
        energia_total_kw=eletrico_total,
        reais_por_hora=reais_por_hora,
        reais_por_dia=reais_por_hora * HORAS_POR_DIA,
        reais_por_mes=reais_por_hora * HORAS_POR_DIA * DIAS_POR_MES,
    )


def calcular_custo(balanco: BalancoTermico, tarifas: Tarifas) -> Custo:
    """O custo de uma cadeia recém-resolvida."""
    return calcular_custo_de_totais(
        balanco.q_refrigeracao_kw,
        balanco.q_aquecimento_kw,
        balanco.agua_umidificacao_kg_h,
        tarifas,
    )
