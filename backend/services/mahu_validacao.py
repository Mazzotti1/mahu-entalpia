"""Validação cruzada entre campos da leitura do MAHU.

A confiança por campo não pega o erro que mais dói. Na leitura #28 de produção os quatro
campos do bloco esquerdo saíram errados ao mesmo tempo — deriva do alinhamento, não dígito
trocado — e cada um deles, isolado, parecia uma leitura boa: confiança alta e valor dentro
da faixa física. O que denuncia esse caso é a relação ENTRE os campos.

Os validadores aqui são baratos porque a planta oferece âncoras de graça:

  - a umidade absoluta de saída é mantida no setpoint, então W(TT07, MT07) tem que dar
    7,30 g/kg. Nas 29 leituras de produção o desvio absoluto médio foi de 0,028 g/kg e o
    máximo de 1,2%. Qualquer coisa muito fora disso é erro de leitura, não de planta.
  - o ar atravessa o MAHU esfriando, então TT01 > TT_04 > TT_06 sempre vale. Valeu em
    28 das 29 leituras; a exceção foi a #28.

Ver docs/especificacao-processo-mahu.md §7.2, §7.3 e §7.5.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from backend.services.psicrometria import (
    calcular_entalpia,
    umidade_absoluta,
    umidade_absoluta_saturacao,
)


@dataclass(frozen=True)
class Aviso:
    codigo: str
    mensagem: str
    # Campos a destacar na conferência. Um aviso sem campo apontado não ajuda ninguém.
    campos: tuple[str, ...]


@dataclass(frozen=True)
class LeituraAnterior:
    """Leitura recente da mesma planta, para checar continuidade."""

    valores: Mapping[str, float]
    minutos: float


def _env_float(nome: str, padrao: float) -> float:
    bruto = os.environ.get(nome)
    if not bruto:
        return padrao
    try:
        return float(bruto)
    except ValueError as exc:
        raise ValueError(f"{nome} precisa ser um número, e veio {bruto!r}.") from exc


# Setpoint de umidade absoluta na saída. Vira parâmetro do processo quando o motor da
# Parte I existir; até lá mora aqui, porque é a âncora do validador mais forte.
W_SAIDA_SETPOINT = _env_float("MAHU_W_SAIDA_SETPOINT", 7.30)

# 2x o desvio máximo observado em produção (1,2%). Estreitar demais transformaria excursão
# real da planta em aviso; alargar demais deixaria passar troca de dígito.
TOLERANCIA_W_SAIDA = _env_float("MAHU_TOLERANCIA_W_SAIDA", 0.025)

# O PV do PID e o par TT07/MT07 descrevem o mesmo estado, mas são instrumentos diferentes.
TOLERANCIA_UMD_ABS = _env_float("MAHU_TOLERANCIA_UMD_ABS", 0.05)

# Folgado de propósito: comparar o PV de entalpia com h(TT_04) pressupõe que P2 está
# saturado, que é a modelagem atual e não um fato medido.
TOLERANCIA_ENTALPIA = _env_float("MAHU_TOLERANCIA_ENTALPIA", 0.10)

# Janela em que duas leituras descrevem praticamente a mesma condição de planta.
JANELA_CONTINUIDADE_MIN = _env_float("MAHU_JANELA_CONTINUIDADE_MIN", 15.0)
SALTO_TEMPERATURA = _env_float("MAHU_SALTO_TEMPERATURA", 2.0)
SALTO_UMIDADE = _env_float("MAHU_SALTO_UMIDADE", 5.0)

# O PV do sensor de umidade absoluta da entrada e o par TT01/MT_01 descrevem o mesmo estado.
TOLERANCIA_W_ENTRADA = _env_float("MAHU_TOLERANCIA_W_ENTRADA", 0.05)

_TEMPERATURAS = ("tt01", "tt02", "tt04", "tt06", "tt07")
_UMIDADES = ("mt_01", "mt07")


def validar_leitura(
    valores: Mapping[str, float],
    anterior: LeituraAnterior | None = None,
) -> list[Aviso]:
    """Avisos sobre a coerência da leitura. Lista vazia = nada suspeito.

    Cada validador roda só se os campos de que precisa estiverem presentes: uma leitura
    parcial já é sinalizada por `missing_keys` e não precisa de aviso redundante.
    """
    avisos: list[Aviso] = []
    _validar_umidade_de_saida(valores, avisos)
    _validar_cadeia_de_resfriamento(valores, avisos)
    _validar_saturacao_em_p2(valores, avisos)
    _validar_umd_abs_informativo(valores, avisos)
    _validar_w_de_entrada(valores, avisos)
    _validar_entalpia_informativa(valores, avisos)
    _validar_continuidade(valores, anterior, avisos)
    return avisos


def _tem(valores: Mapping[str, float], *chaves: str) -> bool:
    return all(valores.get(chave) is not None for chave in chaves)


def _validar_umidade_de_saida(valores: Mapping[str, float], avisos: list[Aviso]) -> None:
    if not _tem(valores, "tt07", "mt07"):
        return
    w = umidade_absoluta(valores["tt07"], valores["mt07"])
    desvio = abs(w - W_SAIDA_SETPOINT) / W_SAIDA_SETPOINT
    if desvio <= TOLERANCIA_W_SAIDA:
        return
    avisos.append(
        Aviso(
            codigo="w_saida_fora_do_setpoint",
            mensagem=(
                f"TT07 e MT07 dão umidade absoluta de {w:.2f} g/kg, e a planta mantém "
                f"{W_SAIDA_SETPOINT:.2f} g/kg ({desvio * 100:.1f}% de desvio). "
                "Confira os dois valores."
            ),
            campos=("tt07", "mt07"),
        )
    )


def _validar_cadeia_de_resfriamento(valores: Mapping[str, float], avisos: list[Aviso]) -> None:
    # TT_02 entra pelo lado do resfriamento apenas: entre TT01 e TT_02 está a serpentina de
    # PRÉ-AQUECIMENTO, e ali o ar esquenta. Cobrar TT01 > TT_02 acusaria de erro a única
    # etapa do MAHU em que a temperatura sobe.
    for antes, depois in (("tt01", "tt04"), ("tt02", "tt04"), ("tt04", "tt06")):
        if not _tem(valores, antes, depois):
            continue
        if valores[antes] > valores[depois]:
            continue
        avisos.append(
            Aviso(
                codigo="cadeia_de_resfriamento",
                mensagem=(
                    f"{antes.upper()} = {valores[antes]:.2f} °C não é maior que "
                    f"{depois.upper()} = {valores[depois]:.2f} °C, mas o ar só esfria "
                    "ao atravessar o MAHU."
                ),
                campos=(antes, depois),
            )
        )


def _validar_saturacao_em_p2(valores: Mapping[str, float], avisos: list[Aviso]) -> None:
    """P2 é modelado como saturado em TT_04, o que exige o ar de entrada mais úmido que ele."""
    if not _tem(valores, "tt01", "mt_01", "tt04"):
        return
    w1 = umidade_absoluta(valores["tt01"], valores["mt_01"])
    w_sat = umidade_absoluta_saturacao(valores["tt04"])
    if w1 >= w_sat:
        return
    avisos.append(
        Aviso(
            codigo="p2_nao_satura",
            mensagem=(
                f"O ar de entrada tem {w1:.2f} g/kg, abaixo dos {w_sat:.2f} g/kg de "
                f"saturação a TT_04 = {valores['tt04']:.2f} °C: com esses valores a "
                "serpentina não condensaria."
            ),
            campos=("tt01", "mt_01", "tt04"),
        )
    )


def _validar_umd_abs_informativo(valores: Mapping[str, float], avisos: list[Aviso]) -> None:
    if not _tem(valores, "umd_abs_pv", "tt07", "mt07"):
        return
    w = umidade_absoluta(valores["tt07"], valores["mt07"])
    lido = valores["umd_abs_pv"]
    if abs(w - lido) <= TOLERANCIA_UMD_ABS * max(w, lido):
        return
    avisos.append(
        Aviso(
            codigo="umd_abs_divergente",
            mensagem=(
                f"O PID de umidade absoluta lê {lido:.2f} g/kg, mas TT07 e MT07 dão "
                f"{w:.2f} g/kg. Um dos três foi lido errado."
            ),
            campos=("umd_abs_pv", "tt07", "mt07"),
        )
    )


def _validar_w_de_entrada(valores: Mapping[str, float], avisos: list[Aviso]) -> None:
    """MT TT MAHU 2.1 contra o W que TT01 e MT_01 implicam.

    Vale o mesmo que o validador da saída, e na ponta que mais importa: TT01+MT_01
    posicionam o primeiro ponto das DUAS cartas, então um erro de leitura ali desloca tudo o
    que vem depois. O sensor de umidade absoluta é a única terceira opinião disponível sobre
    esse estado.
    """
    if not _tem(valores, "mt_tt_mahu_21", "tt01", "mt_01"):
        return
    w = umidade_absoluta(valores["tt01"], valores["mt_01"])
    lido = valores["mt_tt_mahu_21"]
    if abs(w - lido) <= TOLERANCIA_W_ENTRADA * max(w, lido):
        return
    avisos.append(
        Aviso(
            codigo="w_entrada_divergente",
            mensagem=(
                f"O sensor MT TT MAHU 2.1 lê {lido:.2f} g/kg, mas TT01 e MT_01 dão "
                f"{w:.2f} g/kg. Como TT01 e MT_01 posicionam o primeiro ponto das duas "
                "cartas, confira os três antes de aplicar."
            ),
            campos=("mt_tt_mahu_21", "tt01", "mt_01"),
        )
    )


def _validar_entalpia_informativa(valores: Mapping[str, float], avisos: list[Aviso]) -> None:
    if not _tem(valores, "tt04_entalpia_pv", "tt04"):
        return
    h = calcular_entalpia(valores["tt04"], umidade_absoluta_saturacao(valores["tt04"]))
    lido = valores["tt04_entalpia_pv"]
    if abs(h - lido) <= TOLERANCIA_ENTALPIA * max(h, lido):
        return
    avisos.append(
        Aviso(
            codigo="entalpia_divergente",
            mensagem=(
                f"O PID de entalpia lê {lido:.2f} kJ/kg, mas TT_04 = {valores['tt04']:.2f} °C "
                f"saturado daria {h:.2f} kJ/kg."
            ),
            campos=("tt04_entalpia_pv", "tt04"),
        )
    )


def _validar_continuidade(
    valores: Mapping[str, float],
    anterior: LeituraAnterior | None,
    avisos: list[Aviso],
) -> None:
    """Duas fotos com poucos minutos de diferença descrevem quase a mesma condição.

    Aviso, nunca rejeição: a planta pode ter mesmo mudado, e sem a telemetria de O5
    acumulada não dá para distinguir deriva real de erro de leitura.
    """
    if anterior is None or anterior.minutos > JANELA_CONTINUIDADE_MIN:
        return

    for chave in _TEMPERATURAS + _UMIDADES:
        atual = valores.get(chave)
        passado = anterior.valores.get(chave)
        if atual is None or passado is None:
            continue
        limite = SALTO_UMIDADE if chave in _UMIDADES else SALTO_TEMPERATURA
        salto = abs(atual - passado)
        if salto <= limite:
            continue
        avisos.append(
            Aviso(
                codigo="salto_temporal",
                mensagem=(
                    f"{chave.upper()} mudou {salto:.2f} em {anterior.minutos:.0f} min "
                    f"({passado:.2f} para {atual:.2f}). Confirme se a planta mudou mesmo."
                ),
                campos=(chave,),
            )
        )
