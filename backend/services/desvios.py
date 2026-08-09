"""Medições do painel confrontadas com o processo que os setpoints preveem.

Depois das decisões B e D, o cálculo passa a sair dos setpoints e TT_04, TT_06, TT07 e
MT07 deixam de definir pontos. Eles não viram lixo por isso: comparados ao processo
calculado, dizem se a planta está cumprindo o controle — que é a pergunta que um operador
de fato faz olhando a carta.

TT01 e MT_01 ficam de fora: são a ENTRADA do processo, não têm previsão contra o que
comparar.
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
# Agrupamento por ponto (revisado): TT01+MT_01 definem P1 (fora desta lista, são entrada).
# TT_04 e a entalpia do PID TT04 formam P2. TT_06 e a umidade absoluta do PID UMD ABS
# formam P3 — os dois descrevem o mesmo estado, após a umidificação (docs
# especificacao-processo-mahu.md, Parte I §1). Antes, `umd_abs_pv` comparava contra P5,
# que é o ponto de TT07/MT07: agrupamento errado, corrigido aqui.
_COMPARACOES: list[tuple[str, str, str, str, Callable[[Estado], float]]] = [
    ("tt04", "P2", "TBS", "°C", lambda e: e.tbs),
    ("tt04_entalpia_pv", "P2", "h", "kJ/kg", lambda e: e.entalpia),
    ("tt06", "P3", "TBU", "°C", lambda e: e.tbu),
    ("umd_abs_pv", "P3", "W", "g/kg", lambda e: e.w),
    ("tt07", "P5", "TBS", "°C", lambda e: e.tbs),
    ("mt07", "P5", "UR", "%", lambda e: e.ur),
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
