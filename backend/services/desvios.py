"""Medições do painel confrontadas com o processo que os setpoints preveem.

Depois das decisões B e D, o cálculo passa a sair dos setpoints e TT_04, TT_06, TT07 e
MT07 deixam de definir pontos. Eles não viram lixo por isso: comparados ao processo
calculado, dizem se a planta está cumprindo o controle — que é a pergunta que um operador
de fato faz olhando a carta.

TT01 e MT_01 ficam de fora: são a ENTRADA do processo, não têm previsão contra o que
comparar.

Desde a divisão em Carta Atual (medida) e Carta Calculada, os mesmos campos aparecem em
dois papéis: em `processo_medido.py` eles POSICIONAM os pontos da Carta Atual; aqui eles
são conferidos contra a Carta Calculada. A tabela de desvios é, literalmente, a distância
entre as duas cartas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from backend.services.processo import Processo
from backend.services.psicrometria import Estado


@dataclass(frozen=True)
class Desvio:
    campo: str
    ponto: str
    propriedade: str
    unidade: str
    medido: float
    calculado: float

    @property
    def diferenca(self) -> float:
        return self.medido - self.calculado


# campo do painel -> (ponto do processo, rótulo, unidade, como extrair do estado)
#
# É a MESMA lista de slots que a Carta Atual plota (`processo_medido.py`), vista do outro
# lado: lá cada campo posiciona um ponto medido, aqui cada campo é confrontado com o que a
# cadeia dos setpoints previu para o mesmo lugar do MAHU.
#
# TT01 e MT_01 ficam de fora: são a ENTRADA, comuns às duas cartas, e não têm previsão
# contra o que comparar.
#
# `umd_abs_pv` compara contra P5, e não contra P3: por decisão do usuário (16/08/2026) ele é
# a Umidade Absoluta FINAL, do mesmo estado que TT07/MT07. É também o que
# `mahu_validacao._validar_umd_abs_informativo` já assumia — as duas leituras estavam
# divergindo entre si, e agora concordam.
#
# `tt02` compara contra P1 porque a cadeia calculada não tem etapa de pré-aquecimento
# (decisão do usuário: não criar a etapa). O desvio aí mede quanto o pré-aquecedor da planta
# está de fato aquecendo — que é justamente o que a cadeia calculada ignora.
_COMPARACOES: list[tuple[str, str, str, str, Callable[[Estado], float]]] = [
    ("mt_tt_mahu_21", "P1", "W", "g/kg", lambda e: e.w),
    ("tt02", "P1", "TBS", "°C", lambda e: e.tbs),
    ("tt04", "P2", "TBS", "°C", lambda e: e.tbs),
    ("tt04_entalpia_pv", "P2", "h", "kJ/kg", lambda e: e.entalpia),
    # O SP do painel contra o alvo que ESTA execução usou: diz se o app está perseguindo a
    # mesma entalpia que a planta.
    ("tt04_entalpia_sp", "P2", "h (SP)", "kJ/kg", lambda e: e.entalpia),
    ("tt06", "P3", "TBU", "°C", lambda e: e.tbu),
    ("tt07", "P5", "TBS", "°C", lambda e: e.tbs),
    ("mt07", "P5", "UR", "%", lambda e: e.ur),
    ("umd_abs_pv", "P5", "W", "g/kg", lambda e: e.w),
]


def calcular_desvios(processo: Processo, medidos: Mapping[str, float]) -> list[Desvio]:
    return [
        Desvio(
            campo=campo,
            ponto=ponto,
            propriedade=propriedade,
            unidade=unidade,
            medido=medidos[campo],
            calculado=extrair(processo.pontos[ponto]),
        )
        for campo, ponto, propriedade, unidade, extrair in _COMPARACOES
        if medidos.get(campo) is not None and ponto in processo.pontos
    ]
