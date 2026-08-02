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
_COMPARACOES: list[tuple[str, str, str, str, Callable[[Estado], float]]] = [
    ("tt04", "P2", "TBS", "°C", lambda e: e.tbs),
    ("tt06", "P3", "TBU", "°C", lambda e: e.tbu),
    ("tt07", "P5", "TBS", "°C", lambda e: e.tbs),
    ("mt07", "P5", "UR", "%", lambda e: e.ur),
    ("umd_abs_pv", "P5", "W", "g/kg", lambda e: e.w),
    ("tt04_entalpia_pv", "P2", "h", "kJ/kg", lambda e: e.entalpia),
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
