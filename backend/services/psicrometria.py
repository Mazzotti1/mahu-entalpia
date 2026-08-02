"""Propriedades de UM estado do ar úmido, e as inversões para chegar a um estado alvo.

O encadeamento de estados — o processo do MAHU — fica em `processo.py`. Aqui não existe
noção de "antes" e "depois": cada função descreve ou localiza um ponto isolado.
"""

from __future__ import annotations

from dataclasses import dataclass

import psychrolib

psychrolib.SetUnitSystem(psychrolib.SI)

PRESSAO_PADRAO = 101325.0

# Faixa de busca das inversões por bisseção. Cobre com folga qualquer ar de processo em
# HVAC e mantém a busca barata.
_TBS_MIN_BUSCA = -60.0
_TBS_MAX_BUSCA = 90.0
_ITERACOES_BUSCA = 200


@dataclass(frozen=True)
class Estado:
    """Um ponto da carta. `tbs` em °C, `w` em g/kg de ar seco, `pressao_atm` em Pa.

    Só TBS e W são guardados porque só eles são independentes: o resto sai deles e da
    pressão. Guardar propriedades derivadas abriria espaço para um estado inconsistente.
    """

    tbs: float
    w: float
    pressao_atm: float = PRESSAO_PADRAO

    @property
    def _w_kgkg(self) -> float:
        return self.w / 1000.0

    @property
    def ur(self) -> float:
        """Umidade relativa em %."""
        return psychrolib.GetRelHumFromHumRatio(self.tbs, self._w_kgkg, self.pressao_atm) * 100.0

    @property
    def entalpia(self) -> float:
        """kJ/kg de ar seco."""
        return psychrolib.GetMoistAirEnthalpy(self.tbs, self._w_kgkg) / 1000.0

    @property
    def tbu(self) -> float:
        """Temperatura de bulbo úmido em °C."""
        return psychrolib.GetTWetBulbFromHumRatio(self.tbs, self._w_kgkg, self.pressao_atm)

    @property
    def volume_especifico(self) -> float:
        """m³ por kg de ar seco."""
        return psychrolib.GetMoistAirVolume(self.tbs, self._w_kgkg, self.pressao_atm)

    @property
    def ponto_orvalho(self) -> float:
        """Temperatura de ponto de orvalho em °C."""
        return psychrolib.GetTDewPointFromHumRatio(self.tbs, self._w_kgkg, self.pressao_atm)

    @property
    def w_saturacao(self) -> float:
        """Umidade absoluta que o ar comportaria nesta temperatura, em g/kg."""
        return umidade_absoluta_saturacao(self.tbs, self.pressao_atm)

    @property
    def saturado(self) -> bool:
        # Tolerância de 0,001 g/kg: os estados sobre a saturação vêm de inversão numérica
        # e não caem exatamente na curva.
        return self.w >= self.w_saturacao - 1e-3


def umidade_absoluta(tbs: float, ur: float, pressao_atm: float = PRESSAO_PADRAO) -> float:
    """Umidade absoluta em g/kg a partir de TBS (°C) e UR (%)."""
    return psychrolib.GetHumRatioFromRelHum(tbs, ur / 100.0, pressao_atm) * 1000.0


def umidade_absoluta_saturacao(tbs: float, pressao_atm: float = PRESSAO_PADRAO) -> float:
    """Umidade absoluta em g/kg do ar saturado a TBS (°C)."""
    return psychrolib.GetSatHumRatio(tbs, pressao_atm) * 1000.0


def calcular_entalpia(tbs: float, w_gkg: float) -> float:
    """Entalpia em kJ/kg de ar seco a partir de TBS (°C) e umidade absoluta (g/kg)."""
    return psychrolib.GetMoistAirEnthalpy(tbs, w_gkg / 1000.0) / 1000.0


def estado_por_ur(tbs: float, ur: float, pressao_atm: float = PRESSAO_PADRAO) -> Estado:
    return Estado(tbs=tbs, w=umidade_absoluta(tbs, ur, pressao_atm), pressao_atm=pressao_atm)


def estado_saturado(tbs: float, pressao_atm: float = PRESSAO_PADRAO) -> Estado:
    return Estado(
        tbs=tbs, w=umidade_absoluta_saturacao(tbs, pressao_atm), pressao_atm=pressao_atm
    )


def estado_por_h_e_w(h: float, w: float, pressao_atm: float = PRESSAO_PADRAO) -> Estado:
    """Onde a isoentálpica `h` cruza a linha de umidade absoluta `w`."""
    tbs = psychrolib.GetTDryBulbFromEnthalpyAndHumRatio(h * 1000.0, w / 1000.0)
    return Estado(tbs=tbs, w=w, pressao_atm=pressao_atm)


def saturado_por_w(w: float, pressao_atm: float = PRESSAO_PADRAO) -> Estado:
    """Onde a linha de umidade absoluta `w` encontra a saturação — ou seja, o orvalho."""
    tbs = psychrolib.GetTDewPointFromHumRatio(_TBS_MAX_BUSCA, w / 1000.0, pressao_atm)
    return Estado(tbs=tbs, w=w, pressao_atm=pressao_atm)


def saturado_por_entalpia(h: float, pressao_atm: float = PRESSAO_PADRAO) -> Estado:
    """Onde a isoentálpica `h` encontra a curva de saturação.

    Por bisseção porque não há inversa fechada: sobre a saturação, W depende de T pela
    pressão de vapor, e a entalpia depende dos dois. A entalpia do ar saturado cresce
    monotonicamente com a temperatura, o que torna a bisseção segura.
    """
    minimo, maximo = _TBS_MIN_BUSCA, _TBS_MAX_BUSCA
    for _ in range(_ITERACOES_BUSCA):
        meio = (minimo + maximo) / 2.0
        if calcular_entalpia(meio, umidade_absoluta_saturacao(meio, pressao_atm)) < h:
            minimo = meio
        else:
            maximo = meio
    return estado_saturado((minimo + maximo) / 2.0, pressao_atm)


def calcular_ponto(
    *,
    tbs: float,
    ur: float | None = None,
    entalpia: float | None = None,
    w_abs: float | None = None,
    pressao_atm: float = PRESSAO_PADRAO,
) -> dict:
    if w_abs is not None:
        w_kgkg = w_abs / 1000.0
        fonte = "w_abs"
    elif ur is not None:
        w_kgkg = psychrolib.GetHumRatioFromRelHum(tbs, ur / 100.0, pressao_atm)
        fonte = "ur"
    elif entalpia is not None:
        w_kgkg = (entalpia - 1.006 * tbs) / (2501 + 1.86 * tbs)
        fonte = "entalpia"
    else:
        raise ValueError("Informar UR, entalpia ou w_abs.")

    if w_kgkg <= 0:
        raise ValueError("A umidade absoluta calculada ficou inválida (<= 0).")

    ur_calc = psychrolib.GetRelHumFromHumRatio(tbs, w_kgkg, pressao_atm) * 100.0
    # Um ponto SOBRE a curva de saturação é legítimo — P2, P3 e P4 do processo estão lá — e
    # a inversão numérica que o coloca ali erra na 12ª casa, o que bastava para uma
    # comparação exata com 100 recusá-lo. A folga também absorve o arredondamento de duas
    # casas com que os valores voltam do navegador, e continua estreita o bastante para
    # barrar entrada de fato supersaturada (o caso conhecido dá 107%).
    if ur_calc > 100.5:
        raise ValueError(f"Combinação de entrada gera UR de {ur_calc:.1f}%, acima de 100%.")
    ur_calc = min(ur_calc, 100.0)

    h_calc_jkg = psychrolib.GetMoistAirEnthalpy(tbs, w_kgkg)
    tbu_calc = psychrolib.GetTWetBulbFromHumRatio(tbs, w_kgkg, pressao_atm)
    volume_calc = psychrolib.GetMoistAirVolume(tbs, w_kgkg, pressao_atm)
    ponto_orvalho = psychrolib.GetTDewPointFromHumRatio(tbs, w_kgkg, pressao_atm)

    return {
        "tbs": round(tbs, 2),
        "w": round(w_kgkg * 1000.0, 2),
        "ur": round(ur_calc, 2),
        "entalpia": round(h_calc_jkg / 1000.0, 2),
        "tbu": round(tbu_calc, 2),
        "volume_especifico": round(volume_calc, 3),
        "ponto_orvalho": round(ponto_orvalho, 2),
        "fonte_calculo": fonte,
    }
