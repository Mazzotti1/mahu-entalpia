from __future__ import annotations

from backend.models import MahuCamposInput, SimulacaoInput

# Metadados de cada campo lido do monitor MAHU.
# faixa = intervalo fisicamente plausível, usado para rejeitar leituras OCR absurdas.
CAMPOS = [
    ("mt_01", "MT_01", "%", (0.0, 100.0), True),
    ("tt01", "TT01", "°C", (-10.0, 60.0), True),
    ("tt04", "TT_04", "°C", (-10.0, 60.0), True),
    ("tt06", "TT_06", "°C", (-10.0, 60.0), True),
    ("mt07", "MT07", "%", (0.0, 100.0), True),
    ("tt07", "TT07", "°C", (-10.0, 60.0), True),
    # Informativos: servem de conferência, não entram no cálculo dos pontos.
    # PID UMD ABS PV descreve o mesmo estado que MT07/TT07 (7,30 g/kg <-> ~46,5% a 21,2 °C),
    # mas fica num bloco de 3 linhas com 17 px entre SP, PV e MV: a folga necessária para
    # tolerar o erro da retificação invade a linha vizinha e o OCR passaria a poder ler o
    # setpoint como se fosse o PV. MT07 é fonte grande e isolada, então é ele que fixa P4.
    ("umd_abs_pv", "PID UMD ABS PV", "g/kg", (0.0, 30.0), False),
    ("tt04_entalpia_pv", "PID TT04 ENTALPIA PV", "kJ/kg", (0.0, 120.0), False),
]

CAMPOS_OBRIGATORIOS = [key for key, _, _, _, obrigatorio in CAMPOS if obrigatorio]


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
