from __future__ import annotations

import psychrolib

psychrolib.SetUnitSystem(psychrolib.SI)


def calcular_ponto(
    *,
    tbs: float,
    ur: float | None = None,
    entalpia: float | None = None,
    w_abs: float | None = None,
    pressao_atm: float = 101325.0,
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
    if ur_calc > 100.0:
        raise ValueError("Combinação de entrada gera UR acima de 100%.")

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
