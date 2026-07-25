from __future__ import annotations

import re
from functools import lru_cache

import cv2
import numpy as np
from pydantic import ValidationError

from backend.models import MahuCampoOCR, MahuCamposInput
from backend.services.mahu import CAMPOS, CAMPOS_OBRIGATORIOS, construir_simulacao

# Espaço canônico em que as ROIs foram medidas (proporção 2,5:1 da tela do MAHU).
CANON_WIDTH = 1200
CANON_HEIGHT = 480
# A retificação é feita neste múltiplo do espaço canônico: a foto de um celular tem
# muito mais detalhe que 1200 px de largura, e recortar de um quadro reduzido jogaria
# essa resolução fora justamente onde ela importa (dígitos de ~10 px).
SUPERSAMPLE = 4

# Fração do quadro que a tela detectada precisa ocupar para a retificação valer a pena.
MIN_SCREEN_AREA_RATIO = 0.25
# Acima disso o "quadrilátero" achado é a borda do próprio quadro: a foto já é um
# recorte da tela e um resize simples basta.
MAX_SCREEN_AREA_RATIO = 0.98
# Quanto um quadrilátero aninhado precisa ter da área do que o contém para ser tratado
# como a tela dentro da moldura, e não como um painel qualquer desenhado na tela.
MIN_NESTED_AREA_RATIO = 0.55

# Regiões de cada valor no espaço canônico (x1, y1, x2, y2).
ROIS = {
    "mt_01": (12, 124, 66, 145),
    "tt01": (78, 124, 132, 145),
    "tt04": (354, 129, 400, 148),
    "tt06": (598, 143, 645, 162),
    "mt07": (952, 118, 1002, 142),
    "tt07": (1024, 120, 1062, 140),
    "umd_abs_pv": (914, 50, 946, 64),
    "tt04_entalpia_pv": (360, 59, 392, 74),
}

# O monitor MAHU sempre mostra duas casas decimais, o que permite recuperar a vírgula
# quando o OCR a perde ("1220" -> 12,20).
CASAS_DECIMAIS = 2
OCR_ALLOWLIST = "0123456789,.-"
# Concordância e confiança mínimas entre as variantes para a leitura valer como "ok".
MIN_VARIANTES_CONCORDANDO = 2
MIN_CONFIANCA = 0.5


def ler_mahu(image_bytes: bytes) -> dict:
    canonico = _rectify(_decode_image(image_bytes))

    campos: list[MahuCampoOCR] = []
    valores: dict[str, float] = {}

    for key, label, unidade, faixa, obrigatorio in CAMPOS:
        roi = ROIS[key]
        texto, valor, confianca, status = _read_field(_crop(canonico, roi), faixa)
        if valor is not None:
            valores[key] = valor
        campos.append(
            MahuCampoOCR(
                key=key,
                label=label,
                unidade=unidade,
                obrigatorio=obrigatorio,
                raw_text=texto,
                pv=valor,
                confidence=confianca,
                roi=list(roi),
                status=status,
            )
        )

    missing_keys = [campo.key for campo in campos if campo.obrigatorio and campo.pv is None]
    requires_review = any(campo.obrigatorio and campo.status != "ok" for campo in campos)

    suggested_simulacao = None
    if not missing_keys:
        try:
            entrada = MahuCamposInput(**{key: valores[key] for key in CAMPOS_OBRIGATORIOS})
        except ValidationError:
            missing_keys = list(CAMPOS_OBRIGATORIOS)
            requires_review = True
        else:
            suggested_simulacao = construir_simulacao(entrada).model_dump()

    return {
        "campos": [campo.model_dump() for campo in campos],
        "missing_keys": missing_keys,
        "requires_review": requires_review,
        "suggested_simulacao": suggested_simulacao,
    }


def _decode_image(image_bytes: bytes) -> np.ndarray:
    np_bytes = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(np_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Imagem inválida para leitura OCR.")
    return image


def _rectify(frame: np.ndarray) -> np.ndarray:
    """Normaliza a foto no espaço canônico ampliado.

    Se a tela do monitor for identificada no quadro, aplica correção de perspectiva —
    é o que permite fotografar de mão, com moldura e ângulo, e ainda assim recortar as
    ROIs no lugar certo. Sem tela identificada, assume que a foto já é a tela.
    """
    largura = CANON_WIDTH * SUPERSAMPLE
    altura = CANON_HEIGHT * SUPERSAMPLE
    quadrilatero = _find_screen_quad(frame)

    if quadrilatero is None:
        interpolacao = cv2.INTER_AREA if frame.shape[1] > largura else cv2.INTER_CUBIC
        return cv2.resize(frame, (largura, altura), interpolation=interpolacao)

    destino = np.array(
        [[0, 0], [largura - 1, 0], [largura - 1, altura - 1], [0, altura - 1]],
        dtype=np.float32,
    )
    matriz = cv2.getPerspectiveTransform(quadrilatero, destino)
    return cv2.warpPerspective(frame, matriz, (largura, altura), flags=cv2.INTER_CUBIC)


def _find_screen_quad(frame: np.ndarray) -> np.ndarray | None:
    altura, largura = frame.shape[:2]
    area_quadro = float(altura * largura)

    cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    bordas = cv2.Canny(cv2.GaussianBlur(cinza, (5, 5), 0), 40, 140)
    bordas = cv2.dilate(bordas, np.ones((3, 3), np.uint8), iterations=1)
    # RETR_LIST (e não RETR_EXTERNAL) porque a tela é um contorno *interno* ao da moldura
    # do monitor: buscando só os externos, o recorte sai deslocado pela espessura da moldura.
    contornos, _ = cv2.findContours(bordas, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    candidatos: list[tuple[float, np.ndarray]] = []
    for contorno in contornos:
        area = cv2.contourArea(contorno)
        if not area_quadro * MIN_SCREEN_AREA_RATIO <= area <= area_quadro * MAX_SCREEN_AREA_RATIO:
            continue
        perimetro = cv2.arcLength(contorno, True)
        for epsilon in (0.02, 0.03, 0.05):
            aproximacao = cv2.approxPolyDP(contorno, epsilon * perimetro, True)
            if len(aproximacao) == 4 and cv2.isContourConvex(aproximacao):
                candidatos.append((area, aproximacao.reshape(4, 2).astype(np.float32)))
                break

    if not candidatos:
        return None

    # Do maior candidato para dentro: se houver outro quadrilátero aninhado e de tamanho
    # comparável, ele é a tela e o de fora é a moldura.
    candidatos.sort(key=lambda item: item[0], reverse=True)
    _, escolhido = candidatos[0]
    for area, candidato in candidatos[1:]:
        if area >= cv2.contourArea(escolhido) * MIN_NESTED_AREA_RATIO and _dentro(candidato, escolhido):
            escolhido = candidato

    return _order_quad(escolhido)


def _dentro(interno: np.ndarray, externo: np.ndarray) -> bool:
    contorno = externo.reshape(-1, 1, 2).astype(np.float32)
    return all(cv2.pointPolygonTest(contorno, (float(x), float(y)), False) > 0 for x, y in interno)


def _order_quad(pontos: np.ndarray) -> np.ndarray:
    """Ordena os 4 vértices como superior-esquerdo, superior-direito, inferior-direito, inferior-esquerdo."""
    soma = pontos.sum(axis=1)
    diferenca = pontos[:, 0] - pontos[:, 1]
    return np.array(
        [
            pontos[np.argmin(soma)],
            pontos[np.argmax(diferenca)],
            pontos[np.argmax(soma)],
            pontos[np.argmin(diferenca)],
        ],
        dtype=np.float32,
    )


def _crop(canonico: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = roi
    return canonico[
        y1 * SUPERSAMPLE : y2 * SUPERSAMPLE,
        x1 * SUPERSAMPLE : x2 * SUPERSAMPLE,
    ]


def _variants(crop: np.ndarray) -> list[np.ndarray]:
    """Variantes de pré-processamento do mesmo recorte.

    Nenhuma delas acerta todos os campos: o contraste do painel varia entre os blocos
    (texto escuro em caixa branca, texto cinza em fundo cinza). Ler o campo em todas e
    votar é o que dá uma leitura estável.

    São 5 e não mais: variantes morfológicas (erodir o binário para engrossar o traço)
    foram medidas e contribuíam em 4-8 dos 24 campos do conjunto de teste, contra 13-20
    destas, sem corrigir nenhum campo que estas já não acertassem — só custavam tempo.
    """
    cinza = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    equalizado = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(cinza)
    _, otsu = cv2.threshold(cv2.GaussianBlur(cinza, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, otsu_equalizado = cv2.threshold(
        cv2.GaussianBlur(equalizado, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    return [cinza, equalizado, otsu, cv2.bitwise_not(otsu), otsu_equalizado]


def _read_field(
    crop: np.ndarray, faixa: tuple[float, float]
) -> tuple[str | None, float | None, float | None, str]:
    if crop.size == 0:
        return None, None, None, "unreadable"

    engine = _get_ocr_engine()
    confiancas: dict[float, list[float]] = {}
    textos: dict[float, str] = {}
    # Quantas variantes leram o valor com a vírgula visível, sem precisar reconstruí-la.
    explicitos: dict[float, int] = {}

    for variante in _variants(crop):
        for _, texto, confianca in engine.readtext(
            variante, detail=1, paragraph=False, allowlist=OCR_ALLOWLIST
        ):
            valor, inferido = _parse_value(str(texto), faixa)
            if valor is None:
                continue
            confiancas.setdefault(valor, []).append(float(confianca))
            if inferido:
                textos.setdefault(valor, str(texto).strip())
            else:
                explicitos[valor] = explicitos.get(valor, 0) + 1
                # Leitura com separador descreve melhor o campo: sobrepõe a inferida.
                textos[valor] = str(texto).strip()

    if not confiancas:
        return None, None, None, "unreadable"

    # Vence o valor com mais variantes concordando; empate desempata pela confiança somada.
    # Ter enxergado a vírgula não entra aqui de propósito: um "1.0" de confiança 0,21 não
    # deve ganhar de um "730" de 0,59 só por trazer separador. Isso pesa no status, abaixo.
    valor = max(confiancas, key=lambda item: (len(confiancas[item]), sum(confiancas[item])))
    votos = confiancas[valor]
    confianca_media = round(sum(votos) / len(votos), 4)

    # Só é "ok" se alguma variante enxergou a vírgula. Um valor puramente reconstruído é
    # ambíguo por natureza — "220" vira 2,20 e "2120" vira 21,20, ambos plausíveis para
    # uma temperatura — então vai para conferência manual em vez de entrar no cálculo.
    confiavel = (
        len(votos) >= MIN_VARIANTES_CONCORDANDO
        and confianca_media >= MIN_CONFIANCA
        and explicitos.get(valor, 0) >= 1
    )
    status = "ok" if confiavel else "low_confidence"
    return textos[valor], valor, confianca_media, status


def _parse_value(texto: str, faixa: tuple[float, float]) -> tuple[float | None, bool]:
    """Converte o texto do OCR em número, ou (None, False) se não for plausível.

    Devolve também se a vírgula foi inferida, porque uma leitura reconstruída merece
    menos confiança que uma em que o OCR viu o separador.
    """
    minimo, maximo = faixa
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

    # O painel mostra sempre 2 decimais. Uma leitura curta demais perdeu caracteres e
    # não dá para reconstruir: é o que impede um "0" ou "53" solto de virar valor válido.
    minimo_digitos = 2 if tem_separador else CASAS_DECIMAIS + 1
    if len(digitos) < minimo_digitos:
        return None, False

    if tem_separador:
        valor = float(bruto)
        return (round(valor, CASAS_DECIMAIS), False) if minimo <= valor <= maximo else (None, False)

    # Sem separador, os dígitos são o valor multiplicado por 100 ("870" -> 8,70).
    valor = float(bruto) / (10**CASAS_DECIMAIS)
    return (round(valor, CASAS_DECIMAIS), True) if minimo <= valor <= maximo else (None, False)


@lru_cache(maxsize=1)
def _get_ocr_engine():
    # Import tardio: easyocr carrega torch e os modelos de reconhecimento. Mantendo-o
    # aqui, uma instalação incompleta falha apenas em /api/mahu/ler, e não derruba a
    # API inteira no import de routes/pontos.py.
    import easyocr

    return easyocr.Reader(["en"], gpu=False, verbose=False)
