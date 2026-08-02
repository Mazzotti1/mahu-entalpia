from __future__ import annotations

from backend.models import MahuCamposInput, SimulacaoInput


def construir_simulacao(campos: MahuCamposInput) -> SimulacaoInput:
    """Traduz os campos do monitor MAHU nos 4 pontos do processo psicrométrico.

    P1 ar de retorno (TT01 + MT_01)
    P2 saída da serpentina (TT_04, saturado): o ar de P1 tem orvalho ~13 °C, logo
       ao ser resfriado até TT_04 já condensa e sai sobre a curva de saturação.
    P3 ar resfriado saturado (TT_06)
    P4 ar de insuflamento (TT07 + MT07), o mesmo par temperatura+umidade relativa de P1
    """
    return SimulacaoInput(
        nome="Simulação MAHU via OCR",
        descricao="Pontos extraídos da imagem do monitor MAHU.",
        pontos=[
            {"label": "P1", "tbs": campos.tt01, "ur": campos.mt_01},
            {"label": "P2", "tbs": campos.tt04, "ur": 100.0},
            {"label": "P3", "tbs": campos.tt06, "ur": 100.0},
            {"label": "P4", "tbs": campos.tt07, "ur": campos.mt07},
        ],
    )
