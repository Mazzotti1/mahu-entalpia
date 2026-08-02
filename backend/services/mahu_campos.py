"""Metadados dos campos lidos do monitor MAHU.

Sem dependência externa nenhuma — nem pydantic, nem OpenCV, nem o motor de OCR. É o que
permite testar as faixas e a resolução do display sem montar o ambiente completo, e o que
mantém a direção das dependências clara:

    mahu_campos (puro) <- mahu_parse (puro) <- mahu_ocr (OpenCV + easyocr)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Campo:
    """Metadados de um campo lido do monitor MAHU.

    `casas_decimais` é quantas casas o display mostra, e é o que permite reconstruir a
    vírgula quando o OCR a perde. NÃO é global: medido sobre as 29 leituras de produção,
    TT_04 e TT_06 mostram uma casa e os demais mostram duas — os valores desses dois
    terminaram em zero na segunda casa em 29 de 29 leituras, o que por acaso teria
    probabilidade 10^-29. Ver docs/especificacao-processo-mahu.md §7.1.

    Duas faixas, e não uma, porque respondem perguntas diferentes:

    `plausivel` é o limite físico do sensor. Fora dele a leitura é descartada.

    `esperada` é a faixa de operação medida. Dentro dela a leitura vale como "ok"; fora
    dela vira "low_confidence" e vai para conferência em vez de entrar no cálculo. É o
    que separa um dígito trocado de uma condição incomum de planta — a faixa física
    sozinha é larga demais para isso (aceitava TT_04 = 1,18 °C sem reclamar).
    """

    key: str
    label: str
    unidade: str
    casas_decimais: int
    plausivel: tuple[float, float]
    esperada: tuple[float, float]
    obrigatorio: bool


# As faixas `esperada` vêm das 29 leituras de produção de 29-30/07/2026
# (docs/especificacao-processo-mahu.md §6), com folga de ~20% sobre o observado. Nessa
# largura elas não produzem nenhum falso positivo no histórico e ainda assim marcariam
# 3 dos 4 campos corrompidos da leitura #28.
#
# Uma troca de estação desloca todas elas. Por isso são sobrescrevíveis sem rebuild:
#     MAHU_FAIXAS_ESPERADAS='{"tt01": [10, 28], "mt_01": [50, 100]}'
CAMPOS: list[Campo] = [
    Campo("mt_01", "MT_01", "%", 2, (0.0, 100.0), (60.0, 95.0), True),
    Campo("tt01", "TT01", "°C", 2, (-10.0, 60.0), (14.0, 24.0), True),
    Campo("tt04", "TT_04", "°C", 1, (-10.0, 60.0), (9.0, 15.0), True),
    Campo("tt06", "TT_06", "°C", 1, (-10.0, 60.0), (7.0, 11.0), True),
    Campo("mt07", "MT07", "%", 2, (0.0, 100.0), (43.0, 58.0), True),
    Campo("tt07", "TT07", "°C", 2, (-10.0, 60.0), (17.0, 23.0), True),
    # `obrigatorio=False` não quer mais dizer "descartável": desde O6.4 os dois são
    # conferidos, persistidos e comparados com o processo (services/desvios.py). O que a
    # marca significa é que a AUSÊNCIA deles não bloqueia a leitura — o bloco SP/PV/MV com
    # 17 px entre linhas é o recorte mais arriscado da tela, e falhar nele não pode
    # invalidar os seis campos que saíram bem.
    #
    # Decisão B (§4, fechada em 02/08/2026) resolveu o que eles significam: SP calcula, PV
    # vira desvio. Então nenhum dos dois DEFINE ponto — `entalpia_alvo` continua vindo dos
    # setpoints. O que O6.4 entrega é o par sugerido/aplicado destes campos, que é o que
    # faltava para o afinador poder medi-los.
    # PID UMD ABS PV descreve o mesmo estado que MT07/TT07 (7,30 g/kg <-> ~46,5% a 21,2 °C),
    # mas fica num bloco de 3 linhas com 17 px entre SP, PV e MV: a folga necessária para
    # tolerar o erro da retificação invade a linha vizinha e o OCR passaria a poder ler o
    # setpoint como se fosse o PV. MT07 é fonte grande e isolada, então é ele que fixa P4.
    #
    # As casas decimais destes dois não foram medidas contra produção — eles não são
    # persistidos, então o snapshot não os contém. Duas casas é o que o painel mostra nas
    # fotos de docs/fotosMahu; confirmar quando a telemetria de O5 existir.
    Campo("umd_abs_pv", "PID UMD ABS PV", "g/kg", 2, (0.0, 30.0), (6.0, 9.0), False),
    Campo("tt04_entalpia_pv", "PID TT04 ENTALPIA PV", "kJ/kg", 2, (0.0, 120.0), (25.0, 45.0), False),
]

ENV_FAIXAS_ESPERADAS = "MAHU_FAIXAS_ESPERADAS"


def aplicar_faixas_do_ambiente(campos: list[Campo]) -> list[Campo]:
    """Sobrescreve as faixas `esperada` a partir de MAHU_FAIXAS_ESPERADAS.

    Falha alto em configuração inválida em vez de seguir com a faixa antiga: um JSON com
    erro de digitação passaria despercebido e as leituras continuariam sendo classificadas
    pela faixa de outra estação, que é justamente o que a variável existe para corrigir.
    """
    bruto = os.environ.get(ENV_FAIXAS_ESPERADAS)
    if not bruto:
        return campos

    try:
        overrides = json.loads(bruto)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{ENV_FAIXAS_ESPERADAS} não é um JSON válido: {exc}") from exc
    if not isinstance(overrides, dict):
        raise ValueError(f"{ENV_FAIXAS_ESPERADAS} precisa ser um objeto JSON campo -> [min, max].")

    desconhecidos = set(overrides) - {campo.key for campo in campos}
    if desconhecidos:
        raise ValueError(
            f"{ENV_FAIXAS_ESPERADAS} cita campos inexistentes: {', '.join(sorted(desconhecidos))}."
        )

    def faixa(key: str, valor: object) -> tuple[float, float]:
        if not isinstance(valor, (list, tuple)) or len(valor) != 2:
            raise ValueError(f"{ENV_FAIXAS_ESPERADAS}[{key}] precisa ser [min, max].")
        try:
            minimo, maximo = (float(limite) for limite in valor)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{ENV_FAIXAS_ESPERADAS}[{key}]: limites precisam ser números.") from exc
        if minimo >= maximo:
            raise ValueError(f"{ENV_FAIXAS_ESPERADAS}[{key}]: min precisa ser menor que max.")
        return minimo, maximo

    return [
        replace(campo, esperada=faixa(campo.key, overrides[campo.key]))
        if campo.key in overrides
        else campo
        for campo in campos
    ]


CAMPOS = aplicar_faixas_do_ambiente(CAMPOS)

CAMPOS_POR_KEY = {campo.key: campo for campo in CAMPOS}
CAMPOS_OBRIGATORIOS = [campo.key for campo in CAMPOS if campo.obrigatorio]
# Tudo que o usuário confere e que volta ao backend — inclui os do bloco SP/PV/MV, que são
# opcionais no payload mas não descartáveis. É esta lista, e não a de obrigatórios, que
# define o que entra no corpus e o que vira desvio.
CAMPOS_CONFERIVEIS = [campo.key for campo in CAMPOS]
