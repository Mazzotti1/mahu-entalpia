from __future__ import annotations

import os
from functools import lru_cache

import cv2
import numpy as np

from backend.models import MahuCampoOCR
from backend.services.mahu_campos import CAMPOS, Campo
from backend.services.mahu_parse import (
    descrever_faixa_esperada,
    fora_da_faixa_esperada,
    parse_valor,
)

# Espaço canônico em que as ROIs foram medidas (proporção 2,5:1 da tela do MAHU).
CANON_WIDTH = 1200
CANON_HEIGHT = 480
# A retificação é feita neste múltiplo do espaço canônico: a foto de um celular tem
# muito mais detalhe que 1200 px de largura, e recortar de um quadro reduzido jogaria
# essa resolução fora justamente onde ela importa (dígitos de ~10 px).
SUPERSAMPLE = 4

# --- Alinhamento por gabarito -------------------------------------------------------
# O painel é uma tela de software fixa: o desenho (dutos, ventiladores, rótulos) é idêntico
# em qualquer foto e só os números mudam. Casar a foto contra um gabarito por homografia
# resolve enquadramento, escala e perspectiva de uma vez, o que a detecção de quadrilátero
# sozinha não faz — ela falha justamente quando a foto já vem recortada na tela e não há
# moldura para encontrar.
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "mahu_template.png")
# Escala em que o casamento acontece: barata e com detalhe de sobra para os keypoints.
MATCH_WIDTH = CANON_WIDTH
MATCH_HEIGHT = CANON_HEIGHT
# Abaixo disso a homografia não é confiável e o código cai na retificação por quadrilátero.
MIN_HOMOGRAPHY_INLIERS = 25
# Razão de Lowe: descarta casamentos ambíguos entre descritores parecidos.
LOWE_RATIO = 0.75
RANSAC_REPROJ_THRESHOLD = 3.0

# Fração do quadro que a tela detectada precisa ocupar para a retificação valer a pena.
MIN_SCREEN_AREA_RATIO = 0.25
# Acima disso o "quadrilátero" achado é a borda do próprio quadro: a foto já é um
# recorte da tela e um resize simples basta.
MAX_SCREEN_AREA_RATIO = 0.98
# Quanto um quadrilátero aninhado precisa ter da área do que o contém para ser tratado
# como a tela dentro da moldura, e não como um painel qualquer desenhado na tela.
MIN_NESTED_AREA_RATIO = 0.55

# Regiões de cada valor no espaço canônico (x1, y1, x2, y2).
#
# Medidas como a união das caixas de texto detectadas em 9 fotos já alinhadas ao gabarito,
# mais 3 px de margem. Antes do alinhamento elas precisavam de folga generosa para tolerar
# a variação de enquadramento, e essa folga fazia o recorte engolir a unidade da linha de
# baixo ("12,20" + "°C" vira lixo no OCR). Com a homografia a folga deixou de ser
# necessária. Ao remexer nisso, meça de novo sobre imagens alinhadas — não sobre fotos cruas.
ROIS = {
    "mt_01": (18, 124, 61, 145),
    "tt01": (79, 124, 120, 145),
    "tt04": (358, 129, 393, 146),
    "tt06": (605, 143, 635, 160),
    "mt07": (960, 120, 996, 139),
    "tt07": (1024, 120, 1059, 140),
    "umd_abs_pv": (919, 50, 942, 62),
    "tt04_entalpia_pv": (360, 59, 387, 72),
}

OCR_ALLOWLIST = "0123456789,.-"
# Concordância e confiança mínimas entre as variantes para a leitura valer como "ok".
MIN_VARIANTES_CONCORDANDO = 2
MIN_CONFIANCA = 0.5


def ler_mahu(image_bytes: bytes) -> dict:
    """Imagem -> campos lidos. Só o que depende da foto.

    A coerência entre campos (services/mahu_validacao.py), a telemetria e a montagem da
    simulação ficam com o chamador: nada disso precisa de OpenCV, e misturar aqui obrigaria
    o ambiente completo para testar qualquer uma das três.
    """
    canonico = _rectify(_decode_image(image_bytes))

    campos: list[MahuCampoOCR] = []
    valores: dict[str, float] = {}

    for campo in CAMPOS:
        roi = ROIS[campo.key]
        texto, valor, confianca, status, motivo = _read_field(_crop(canonico, roi), campo)
        if valor is not None:
            valores[campo.key] = valor
        campos.append(
            MahuCampoOCR(
                key=campo.key,
                label=campo.label,
                unidade=campo.unidade,
                obrigatorio=campo.obrigatorio,
                raw_text=texto,
                pv=valor,
                confidence=confianca,
                roi=list(roi),
                status=status,
                motivo=motivo,
            )
        )

    return {
        "campos": campos,
        "missing_keys": [campo.key for campo in campos if campo.obrigatorio and campo.pv is None],
        # Só os campos que o OCR conseguiu ler, para a validação cruzada e a montagem.
        "valores": valores,
    }


def _decode_image(image_bytes: bytes) -> np.ndarray:
    np_bytes = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(np_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Imagem inválida para leitura OCR.")
    return image


def _rectify(frame: np.ndarray) -> np.ndarray:
    """Normaliza a foto no espaço canônico ampliado.

    Tenta primeiro casar a foto contra o gabarito por homografia, que é o caminho preciso:
    resolve enquadramento, escala e perspectiva juntos, e não depende de a moldura do
    monitor aparecer. Só quando o casamento não converge é que recai na detecção do
    quadrilátero da tela, e daí no redimensionamento cru.
    """
    alinhado = _align_to_template(frame)
    if alinhado is not None:
        return alinhado

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


def _match_features(image: np.ndarray) -> np.ndarray:
    """Prepara a imagem para o casamento: escala fixa e contraste normalizado.

    O CLAHE é o que permite casar fotos tiradas sob iluminações diferentes — sem ele os
    descritores de uma foto clara não batem com os de uma escura.
    """
    cinza = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    cinza = cv2.resize(cinza, (MATCH_WIDTH, MATCH_HEIGHT), interpolation=cv2.INTER_AREA)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(cinza)


@lru_cache(maxsize=1)
def _get_template():
    """Descritores SIFT do gabarito, calculados uma vez por processo."""
    template = cv2.imread(TEMPLATE_PATH, cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise FileNotFoundError(f"Gabarito do MAHU não encontrado em {TEMPLATE_PATH}.")
    detector = cv2.SIFT_create(nfeatures=4000)
    keypoints, descritores = detector.detectAndCompute(_match_features(template), None)
    return detector, keypoints, descritores


def _align_to_template(frame: np.ndarray) -> np.ndarray | None:
    """Casa a foto contra o gabarito e devolve o canônico ampliado, ou None se não casar."""
    try:
        detector, kp_gabarito, des_gabarito = _get_template()
    except FileNotFoundError:
        return None

    keypoints, descritores = detector.detectAndCompute(_match_features(frame), None)
    if descritores is None or len(keypoints) < MIN_HOMOGRAPHY_INLIERS:
        return None

    pares = cv2.BFMatcher().knnMatch(descritores, des_gabarito, k=2)
    bons = [
        melhor
        for melhor, segundo in (par for par in pares if len(par) == 2)
        if melhor.distance < LOWE_RATIO * segundo.distance
    ]
    if len(bons) < MIN_HOMOGRAPHY_INLIERS:
        return None

    origem = np.float32([keypoints[m.queryIdx].pt for m in bons]).reshape(-1, 1, 2)
    destino = np.float32([kp_gabarito[m.trainIdx].pt for m in bons]).reshape(-1, 1, 2)
    homografia, mascara = cv2.findHomography(
        origem, destino, cv2.RANSAC, RANSAC_REPROJ_THRESHOLD
    )
    if homografia is None or int(mascara.sum()) < MIN_HOMOGRAPHY_INLIERS:
        return None

    # A homografia foi estimada no espaço de casamento. Compondo com as escalas de entrada
    # e saída, a foto original vai direto ao canônico ampliado numa única reamostragem —
    # passar por um intermediário reduzido jogaria fora a resolução dos dígitos.
    altura_origem, largura_origem = frame.shape[:2]
    escala_entrada = np.array(
        [[MATCH_WIDTH / largura_origem, 0, 0], [0, MATCH_HEIGHT / altura_origem, 0], [0, 0, 1]],
        dtype=np.float64,
    )
    escala_saida = np.array(
        [
            [SUPERSAMPLE * CANON_WIDTH / MATCH_WIDTH, 0, 0],
            [0, SUPERSAMPLE * CANON_HEIGHT / MATCH_HEIGHT, 0],
            [0, 0, 1],
        ],
        dtype=np.float64,
    )
    return cv2.warpPerspective(
        frame,
        escala_saida @ homografia @ escala_entrada,
        (CANON_WIDTH * SUPERSAMPLE, CANON_HEIGHT * SUPERSAMPLE),
        flags=cv2.INTER_CUBIC,
    )


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
    crop: np.ndarray, campo: Campo
) -> tuple[str | None, float | None, float | None, str, str | None]:
    if crop.size == 0:
        return None, None, None, "unreadable", "recorte vazio"

    engine = _get_ocr_engine()
    confiancas: dict[float, list[float]] = {}
    textos: dict[float, str] = {}

    for variante in _variants(crop):
        for _, texto, confianca in engine.readtext(
            variante, detail=1, paragraph=False, allowlist=OCR_ALLOWLIST
        ):
            valor, inferido = parse_valor(str(texto), campo)
            if valor is None:
                continue
            confiancas.setdefault(valor, []).append(float(confianca))
            if inferido:
                textos.setdefault(valor, str(texto).strip())
            else:
                # Leitura com separador descreve melhor o campo: sobrepõe a inferida.
                textos[valor] = str(texto).strip()

    if not confiancas:
        return None, None, None, "unreadable", "nada legível no recorte"

    # Vence o valor com mais variantes concordando; empate desempata pela confiança somada.
    valor = max(confiancas, key=lambda item: (len(confiancas[item]), sum(confiancas[item])))
    votos = confiancas[valor]
    confianca_media = round(sum(votos) / len(votos), 4)

    # A faixa de operação é o que decide se a leitura entra no cálculo. Antes esse papel
    # era de um gate que exigia ter enxergado a vírgula, porque um valor reconstruído era
    # ambíguo ("220" viraria 2,20 e "2120" viraria 21,20, ambos plausíveis para uma
    # temperatura). Com as casas decimais definidas por campo a reconstrução deixou de ser
    # ambígua, e com a faixa esperada o 2,20 é rejeitado por si só — manter o gate só
    # mandava leitura boa para conferência à toa.
    if len(votos) < MIN_VARIANTES_CONCORDANDO:
        motivo = "apenas uma variante da imagem leu este valor"
    elif confianca_media < MIN_CONFIANCA:
        motivo = f"confiança baixa ({confianca_media:.2f})"
    elif fora_da_faixa_esperada(valor, campo):
        motivo = f"fora da faixa de operação ({descrever_faixa_esperada(campo)})"
    else:
        motivo = None

    status = "ok" if motivo is None else "low_confidence"
    return textos[valor], valor, confianca_media, status, motivo


@lru_cache(maxsize=1)
def _get_ocr_engine():
    # Import tardio: easyocr carrega torch e os modelos de reconhecimento. Mantendo-o
    # aqui, uma instalação incompleta falha apenas em /api/mahu/ler, e não derruba a
    # API inteira no import de routes/pontos.py.
    import easyocr

    return easyocr.Reader(["en"], gpu=False, verbose=False)
