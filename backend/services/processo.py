"""O processo do MAHU: encadeia estados do ar e diz o que aconteceu entre eles.

Cinco pontos e um ramo condicional (docs/especificacao-processo-mahu.md, Parte I):

    P1  ar de entrada                       TT01 + MT_01
    P2  saída do conjunto de serpentinas    alvo = entalpia (setpoint)
    P3  após umidificação                   SÓ SE W2 < W de saída; adiabática até saturar
    P4  saída da serpentina de água fria    saturado no setpoint de umidade absoluta
    P5  insuflamento                        aquecido até o setpoint de temperatura

O que este módulo acrescenta em cima de `psicrometria.py` é a noção de *trajetória*. Dois
estados não bastam para dizer o que a serpentina fez: resfriar de 20 °C a 12 °C pode ser
puramente sensível ou cruzar a saturação e condensar no meio do caminho, e a diferença
muda tanto o kW quanto o desenho na carta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backend.services.psicrometria import (
    PRESSAO_PADRAO,
    Estado,
    estado_por_h_e_w,
    estado_saturado,
    saturado_por_entalpia,
    saturado_por_w,
)

TipoEtapa = Literal[
    "resfriamento_sensivel",
    "resfriamento_desumidificacao",
    "aquecimento_sensivel",
    "umidificacao_adiabatica",
    "nula",
]

# Faixa fisicamente aceitável para a pressão atmosférica, em Pa. Existe porque a
# especificação original pedia "101325 kPa", que é mil atmosferas: sem checagem, um erro
# de unidade atravessaria o cálculo inteiro sem reclamar.
PRESSAO_MINIMA = 80_000.0
PRESSAO_MAXIMA = 110_000.0


@dataclass(frozen=True)
class Setpoints:
    """O que a planta persegue. Decisão B: é daqui que saem os alvos, não das medições."""

    # Umidade absoluta na saída, em g/kg.
    w_saida: float = 7.30
    # Temperatura de insuflamento, em °C.
    tbs_final: float = 20.0
    # Entalpia alvo de P2, em kJ/kg. Setpoint independente — ver §4 do documento.
    entalpia_alvo: float = 36.20
    # Vazão volumétrica do MAHU, em m³/h, medida na ENTRADA (decisão A).
    vazao_m3h: float = 36575.0
    pressao_atm: float = PRESSAO_PADRAO


@dataclass(frozen=True)
class Etapa:
    """Uma transformação entre dois pontos consecutivos.

    `tipo` é o que diz ao desenho qual trajetória traçar — reta horizontal, trecho sobre a
    saturação, ou linha de bulbo úmido constante — e ao cálculo de energia se a etapa é
    serpentina quente, fria ou umidificador.
    """

    tipo: TipoEtapa
    de: str
    para: str
    inicio: Estado
    fim: Estado
    # Estado onde a trajetória encontra a saturação, quando ela muda de direção no meio do
    # caminho. `None` quando a etapa é uma reta só.
    joelho: Estado | None = None

    @property
    def ativa(self) -> bool:
        return self.tipo != "nula"

    @property
    def delta_h(self) -> float:
        return self.fim.entalpia - self.inicio.entalpia

    @property
    def delta_w(self) -> float:
        return self.fim.w - self.inicio.w


@dataclass(frozen=True)
class Aviso:
    codigo: str
    mensagem: str


@dataclass(frozen=True)
class Processo:
    pontos: dict[str, Estado]
    etapas: list[Etapa]
    setpoints: Setpoints
    avisos: list[Aviso] = field(default_factory=list)

    @property
    def ordem(self) -> list[str]:
        return ["P1", "P2", "P3", "P4", "P5"]


# --- Transformações ------------------------------------------------------------------


def aquecer_sensivel_ate_tbs(inicio: Estado, tbs: float) -> Estado:
    """Aquecimento a W constante. Nunca cruza a saturação: aquecer afasta dela."""
    return Estado(tbs=tbs, w=inicio.w, pressao_atm=inicio.pressao_atm)


def resfriar_ate_entalpia(inicio: Estado, h_alvo: float) -> tuple[Estado, Estado | None]:
    """Leva o ar até a entalpia alvo pelo conjunto de serpentinas.

    Devolve `(fim, joelho)`. O joelho é onde a trajetória encontra a saturação e passa a
    segui-la, e é `None` quando o percurso é uma reta só.

    Aquecendo, o caminho é sempre sensível. Resfriando, o ar segue a W constante até o
    ponto de orvalho e, dali em diante, condensa: continuar em linha reta produziria ar
    supersaturado, que não existe. É o caso do MAHU em operação normal.
    """
    if h_alvo >= inicio.entalpia:
        return estado_por_h_e_w(h_alvo, inicio.w, inicio.pressao_atm), None

    orvalho = saturado_por_w(inicio.w, inicio.pressao_atm)
    if h_alvo >= orvalho.entalpia:
        # Ainda não chegou a condensar.
        return estado_por_h_e_w(h_alvo, inicio.w, inicio.pressao_atm), None

    return saturado_por_entalpia(h_alvo, inicio.pressao_atm), orvalho


def umidificar_adiabatico_ate_saturacao(inicio: Estado) -> Estado:
    """Umidificação por água, até o ar saturar (decisão C).

    A água evapora tirando calor sensível do próprio ar, então a temperatura de bulbo
    úmido não muda e o estado caminha sobre a linha de TBU constante. Saturado, TBS = TBU,
    e é isso que o TT_06 do painel mede.
    """
    return estado_saturado(inicio.tbu, inicio.pressao_atm)


def resfriar_saturado_ate_w(inicio: Estado, w_alvo: float) -> Estado:
    """Resfriamento sobre a curva de saturação até a umidade absoluta alvo.

    O ar entra saturado e continua saturado enquanto esfria: o excesso de vapor condensa e
    o estado desliza pela curva. Chegar a `w_alvo` é o que fixa a temperatura de saída, que
    é o ponto de orvalho do setpoint.
    """
    return saturado_por_w(w_alvo, inicio.pressao_atm)


# --- Encadeamento --------------------------------------------------------------------


def _classificar_resfriamento(etapa_inicio: Estado, fim: Estado, joelho: Estado | None) -> TipoEtapa:
    if abs(fim.entalpia - etapa_inicio.entalpia) < 1e-9:
        return "nula"
    if fim.entalpia > etapa_inicio.entalpia:
        return "aquecimento_sensivel"
    return "resfriamento_desumidificacao" if joelho is not None else "resfriamento_sensivel"


def resolver_processo(entrada: Estado, setpoints: Setpoints) -> Processo:
    """Encadeia P1..P5 a partir do ar de entrada e dos setpoints."""
    avisos: list[Aviso] = []
    _validar_pressao(setpoints, avisos)

    p1 = entrada
    p2, joelho = resfriar_ate_entalpia(p1, setpoints.entalpia_alvo)
    etapas = [
        Etapa(
            tipo=_classificar_resfriamento(p1, p2, joelho),
            de="P1",
            para="P2",
            inicio=p1,
            fim=p2,
            joelho=joelho,
        )
    ]

    # O ramo condicional do processo. Umidificar só faz sentido se o ar chegou seco demais:
    # com W2 já acima do setpoint, a serpentina fria sozinha alcança o alvo, e é isso que
    # acontece na operação de inverno registrada no snapshot.
    precisa_umidificar = p2.w < setpoints.w_saida
    if precisa_umidificar:
        p3 = umidificar_adiabatico_ate_saturacao(p2)
        etapas.append(
            Etapa(tipo="umidificacao_adiabatica", de="P2", para="P3", inicio=p2, fim=p3)
        )
        if p3.w < setpoints.w_saida:
            avisos.append(
                Aviso(
                    codigo="umidificacao_insuficiente",
                    mensagem=(
                        f"Umidificar até saturar leva a {p3.w:.2f} g/kg, ainda abaixo do "
                        f"setpoint de {setpoints.w_saida:.2f} g/kg. A etapa seguinte teria "
                        "de aquecer em vez de resfriar: o ar de entrada está seco demais "
                        "para este setpoint."
                    ),
                )
            )
    else:
        # P3 existe como ponto para a tabela e a carta não terem buraco, mas a etapa é nula.
        p3 = p2
        etapas.append(Etapa(tipo="nula", de="P2", para="P3", inicio=p2, fim=p3))

    p4 = resfriar_saturado_ate_w(p3, setpoints.w_saida)
    etapas.append(
        Etapa(
            tipo="resfriamento_desumidificacao" if p4.w < p3.w else "nula",
            de="P3",
            para="P4",
            inicio=p3,
            fim=p4,
        )
    )

    p5 = aquecer_sensivel_ate_tbs(p4, setpoints.tbs_final)
    etapas.append(
        Etapa(
            tipo="aquecimento_sensivel" if p5.tbs > p4.tbs else "nula",
            de="P4",
            para="P5",
            inicio=p4,
            fim=p5,
        )
    )

    _validar_alvo_alcancavel(p1, p2, setpoints, avisos)

    return Processo(
        pontos={"P1": p1, "P2": p2, "P3": p3, "P4": p4, "P5": p5},
        etapas=etapas,
        setpoints=setpoints,
        avisos=avisos,
    )


def _validar_pressao(setpoints: Setpoints, avisos: list[Aviso]) -> None:
    if PRESSAO_MINIMA <= setpoints.pressao_atm <= PRESSAO_MAXIMA:
        return
    avisos.append(
        Aviso(
            codigo="pressao_fora_da_faixa",
            mensagem=(
                f"Pressão atmosférica de {setpoints.pressao_atm:.0f} Pa fora da faixa "
                f"plausível ({PRESSAO_MINIMA:.0f} a {PRESSAO_MAXIMA:.0f} Pa). "
                "Confira a unidade: o valor é em Pa, não em kPa."
            ),
        )
    )


def _validar_alvo_alcancavel(
    p1: Estado, p2: Estado, setpoints: Setpoints, avisos: list[Aviso]
) -> None:
    if setpoints.entalpia_alvo > p1.entalpia:
        avisos.append(
            Aviso(
                codigo="alvo_exige_aquecimento",
                mensagem=(
                    f"A entalpia alvo ({setpoints.entalpia_alvo:.2f} kJ/kg) é maior que a de "
                    f"entrada ({p1.entalpia:.2f} kJ/kg): a primeira etapa vira aquecimento."
                ),
            )
        )
    if p2.w < setpoints.w_saida and not p2.saturado:
        avisos.append(
            Aviso(
                codigo="p2_seco_sem_saturar",
                mensagem=(
                    f"P2 sai com {p2.w:.2f} g/kg sem ter saturado. O ar precisará de "
                    "umidificação para alcançar o setpoint de saída."
                ),
            )
        )
