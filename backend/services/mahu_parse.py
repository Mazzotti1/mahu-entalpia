"""Texto do OCR -> valor do campo.

Módulo separado de `mahu_ocr` de propósito: aqui não entra nem OpenCV nem easyocr, e é
onde mora a lógica que produziu erro silencioso em produção. Sem a separação, testar a
reconstrução da vírgula exigiria a imagem de 2 GB com torch dentro.
"""

from __future__ import annotations

import re

from backend.services.mahu_campos import Campo


def parse_valor(texto: str, campo: Campo) -> tuple[float | None, bool]:
    """Converte o texto do OCR no valor do campo, ou `(None, False)` se implausível.

    Devolve também se a vírgula foi reconstruída, porque uma leitura em que o OCR viu o
    separador descreve melhor o campo do que uma remontada a partir dos dígitos.
    """
    limpo = re.sub(r"[^0-9,.\-]", "", texto).replace(",", ".")
    # O OCR às vezes devolve mais de um separador ("1.2.20"): vale o último.
    if limpo.count(".") > 1:
        cabeca, _, cauda = limpo.rpartition(".")
        limpo = cabeca.replace(".", "") + "." + cauda

    match = re.search(r"-?\d+(?:\.\d+)?", limpo)
    if not match:
        return None, False

    bruto = match.group(0)
    digitos = re.sub(r"\D", "", bruto)
    tem_separador = "." in bruto

    # O display mostra sempre `casas_decimais` decimais e ao menos um dígito inteiro.
    # Menos dígitos que isso é leitura truncada e não dá para reconstruir: é o que impede
    # um "0" ou um "53" solto de virar valor válido.
    if len(digitos) < campo.casas_decimais + 1:
        return None, False

    if tem_separador:
        valor = float(bruto)
        inferido = False
    else:
        # Sem separador, os dígitos são o valor deslocado pelas casas do display:
        # "870" -> 8,70 num campo de 2 casas, "118" -> 11,8 num de 1 casa.
        valor = float(bruto) / (10**campo.casas_decimais)
        inferido = True

    minimo, maximo = campo.plausivel
    if not minimo <= valor <= maximo:
        return None, False

    # Arredondar na resolução do display descarta precisão que o painel não mostra:
    # um "11.83" lido num campo de 1 casa só pode ter sido 11,8.
    return round(valor, campo.casas_decimais), inferido


def fora_da_faixa_esperada(valor: float, campo: Campo) -> bool:
    minimo, maximo = campo.esperada
    return not minimo <= valor <= maximo


def descrever_faixa_esperada(campo: Campo) -> str:
    minimo, maximo = campo.esperada
    return f"{minimo:g} a {maximo:g} {campo.unidade}"
