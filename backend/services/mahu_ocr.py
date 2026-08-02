from __future__ import annotations

import os
from dataclasses import dataclass, replace
from functools import lru_cache

import cv2
import numpy as np

from backend.models import MahuCampoOCR
from backend.services.mahu_campos import Campo
from backend.services.mahu_metricas import (
    METODO_HOMOGRAFIA,
    METODO_QUADRILATERO,
    METODO_RESIZE,
    Alinhamento,
    Ancora,
    Qualidade,
)
from backend.services.mahu_parse import (
    descrever_faixa_esperada,
    fora_da_faixa_esperada,
    parse_valor,
)
from backend.services.mahu_qualidade import (
    medir_alinhamento,
    medir_ancoras,
    medir_enquadramento,
    medir_foto,
)
from backend.services.perfil_ocr import (
    DERIVA_MAX_ANCORA,
    MIN_CORRELACAO_ANCORA,
    PerfilOCR,
    perfil_ativo,
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

OCR_ALLOWLIST = "0123456789,.-"

# ROIs, limiares e faixas NÃO moram mais aqui: vieram para `perfil_ocr` para poderem ser
# versionados e comparados. Constante de módulo é uma só por processo, e com ela não há como
# rodar o mesmo corpus sob duas configurações sem mutar o módulo no meio da execução.


def ler_mahu(image_bytes: bytes, perfil: PerfilOCR | None = None) -> dict:
    """Imagem -> campos lidos, sob uma configuração explícita. Só o que depende da foto.

    A coerência entre campos (services/mahu_validacao.py), a telemetria e a montagem da
    simulação ficam com o chamador: nada disso precisa de OpenCV, e misturar aqui obrigaria
    o ambiente completo para testar qualquer uma das três.

    Devolve também COMO a foto foi tirada e quão bem ela alinhou. Sem isso a telemetria
    sabe que a leitura errou e não sabe por quê — e é essa correlação que sustenta tanto o
    aviso de "tire outra foto" quanto os limiares que o afinador vai derivar depois.

    `perfil` ausente usa o ativo do processo, que é o caminho de produção. Passá-lo é o que
    permite reprocessar o corpus sob um candidato sem tocar no que a API está servindo — e
    é por isso que ele é parâmetro e não estado global lido lá dentro.
    """
    perfil = perfil or perfil_ativo()
    quadro = _decode_image(image_bytes)
    canonico, alinhamento, qualidade = _rectify(quadro, perfil)
    nitidez, reflexo = medir_foto(canonico, CANON_WIDTH, CANON_HEIGHT)
    qualidade = replace(qualidade, nitidez=nitidez, reflexo=reflexo)

    # Âncoras: mede a deriva do alinhamento PERTO de cada campo, casando um trecho fixo do
    # painel. É a checagem que faltou na #28 — lá a homografia passou no corte global e
    # ainda assim deslocou o bloco esquerdo, e as ROIs daquele lado recortaram o lugar
    # errado sem nada perceber. Só no caminho da homografia: nos outros não há registro
    # bom o bastante para um deslocamento rígido significar alguma coisa.
    ancoras = (
        medir_ancoras(
            canonico, _gabarito_canonico(), perfil.ancoras, CANON_WIDTH, CANON_HEIGHT
        )
        if alinhamento.metodo == METODO_HOMOGRAFIA
        else {}
    )

    campos: list[MahuCampoOCR] = []
    valores: dict[str, float] = {}
    caixas: dict[str, tuple[float, float, float, float]] = {}

    for campo in perfil.campos():
        roi, aviso_ancora = _roi_corrigida(perfil.rois[campo.key], ancoras.get(campo.key))
        lido = _read_field(_crop(canonico, roi), campo, perfil, roi)
        if aviso_ancora is not None:
            lido = replace(
                lido,
                # Nunca melhora o status: a âncora só sabe acusar. Um campo que já era
                # ilegível não vira duvidoso por causa dela.
                status="unreadable" if lido.status == "unreadable" else "low_confidence",
                motivo=aviso_ancora if lido.motivo is None else f"{lido.motivo}; {aviso_ancora}",
            )
        if lido.valor is not None:
            valores[campo.key] = lido.valor
        if lido.caixa is not None:
            caixas[campo.key] = lido.caixa
        campos.append(
            MahuCampoOCR(
                key=campo.key,
                label=campo.label,
                unidade=campo.unidade,
                obrigatorio=campo.obrigatorio,
                raw_text=lido.texto,
                pv=lido.valor,
                confidence=lido.confianca,
                roi=list(roi),
                status=lido.status,
                motivo=lido.motivo,
            )
        )

    return {
        "campos": campos,
        "missing_keys": [campo.key for campo in campos if campo.obrigatorio and campo.pv is None],
        # Só os campos que o OCR conseguiu ler, para a validação cruzada e a montagem.
        "valores": valores,
        "alinhamento": alinhamento,
        "qualidade": qualidade,
        # Sob qual configuração isto foi lido. Vai para a telemetria: sem ele, uma melhora
        # ou uma piora no histórico não pode ser atribuída a nada.
        "perfil_id": perfil.id,
        # Onde o texto estava, no espaço canônico. Não é persistido: o afinador de ROI
        # reprocessa as fotos de qualquer forma, e guardar a caixa de toda leitura seria
        # pagar espaço permanente por um dado que só interessa em bloco.
        "caixas": caixas,
    }


def _roi_corrigida(
    roi: tuple[int, int, int, int], ancora: Ancora | None
) -> tuple[tuple[int, int, int, int], str | None]:
    """Desloca a ROI pela deriva medida na âncora, ou explica por que não dá para confiar.

    Corrigir é melhor que só avisar. A deriva vem do desenho do painel, que é fixo — se o
    rótulo apareceu 6 px à direita, o número ao lado também apareceu, e mover o recorte é a
    resposta certa e exata. Avisar sem corrigir mandaria para conferência uma leitura que
    dava para acertar sozinho.

    Fora dos limites o deslocamento deixa de ser resposta: correlação baixa quer dizer que a
    âncora não foi encontrada (a deriva medida não descreve nada), e deriva grande quer dizer
    que o alinhamento errou demais para um deslocamento rígido consertar. Nos dois casos o
    recorte fica onde está e o campo vai para conferência — é o oposto do que a #28 fez.
    """
    if ancora is None:
        return roi, None

    if ancora.correlacao < MIN_CORRELACAO_ANCORA:
        return roi, f"âncora do campo não confirmada (correlação {ancora.correlacao:.2f})"

    deriva = max(abs(ancora.dx), abs(ancora.dy))
    if deriva > DERIVA_MAX_ANCORA:
        return roi, f"alinhamento deslocado {deriva:.0f} px neste ponto do painel"

    dx, dy = int(round(ancora.dx)), int(round(ancora.dy))
    if dx == 0 and dy == 0:
        return roi, None
    return (roi[0] + dx, roi[1] + dy, roi[2] + dx, roi[3] + dy), None


@lru_cache(maxsize=1)
def _gabarito_canonico() -> np.ndarray:
    """O gabarito em escala canônica, para o casamento das âncoras. Uma vez por processo."""
    template = cv2.imread(TEMPLATE_PATH, cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise FileNotFoundError(f"Gabarito do MAHU não encontrado em {TEMPLATE_PATH}.")
    return cv2.resize(template, (CANON_WIDTH, CANON_HEIGHT), interpolation=cv2.INTER_AREA)


def medir_captura(
    image_bytes: bytes, perfil: PerfilOCR | None = None
) -> tuple[Alinhamento, Qualidade]:
    """Só as métricas da foto, sem ler número nenhum. É o que o guia de câmera consome.

    O que torna isto barato é não chamar o easyocr: são 8 campos × 5 variantes por leitura,
    e é daí que vêm os ~20 s. Sem ele sobra o casamento SIFT, ~150 ms, que é justamente o
    que mede o enquadramento.

    A retificação continua no SUPERSAMPLE, e não numa escala menor. Reamostrar para 1200x480
    direto economizaria uns 30 ms e faria a `nitidez` medir outra coisa: a variância do
    laplaciano depende de como os pixels foram interpolados, e um `warpPerspective` cúbico
    direto dá ~1700 onde o mesmo quadro reduzido do 4x dá ~1100. Os limiares do guia são
    derivados dos valores GRAVADOS pelas leituras, então medir diferente aqui compararia
    número com número de outra régua.
    """
    perfil = perfil or perfil_ativo()
    quadro = _decode_image(image_bytes)

    alinhado = _align_to_template(quadro, perfil)
    if alinhado is None:
        # Sem casamento não há geometria: o guia só precisa saber que falhou, e a instrução
        # correspondente ("encaixe a tela na moldura") não depende de mais nenhum número.
        return Alinhamento(metodo=METODO_RESIZE), Qualidade()

    canonico, alinhamento, qualidade = alinhado
    nitidez, reflexo = medir_foto(canonico, CANON_WIDTH, CANON_HEIGHT)
    return alinhamento, replace(qualidade, nitidez=nitidez, reflexo=reflexo)


def _decode_image(image_bytes: bytes) -> np.ndarray:
    np_bytes = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(np_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Imagem inválida para leitura OCR.")
    return image


def _rectify(frame: np.ndarray, perfil: PerfilOCR) -> tuple[np.ndarray, Alinhamento, Qualidade]:
    """Normaliza a foto no espaço canônico ampliado, dizendo por qual caminho passou.

    Tenta primeiro casar a foto contra o gabarito por homografia, que é o caminho preciso:
    resolve enquadramento, escala e perspectiva juntos, e não depende de a moldura do
    monitor aparecer. Só quando o casamento não converge é que recai na detecção do
    quadrilátero da tela, e daí no redimensionamento cru.

    O caminho percorrido é métrica em si: cair para `quadrilatero` ou `resize` significa
    que o gabarito não casou, e é a informação mais forte de que a foto está ruim — vale
    mesmo antes de qualquer análise dos números lidos.
    """
    alinhado = _align_to_template(frame, perfil)
    if alinhado is not None:
        return alinhado

    largura = CANON_WIDTH * SUPERSAMPLE
    altura = CANON_HEIGHT * SUPERSAMPLE
    quadrilatero = _find_screen_quad(frame)

    if quadrilatero is None:
        interpolacao = cv2.INTER_AREA if frame.shape[1] > largura else cv2.INTER_CUBIC
        return (
            cv2.resize(frame, (largura, altura), interpolation=interpolacao),
            Alinhamento(metodo=METODO_RESIZE),
            Qualidade(),
        )

    destino = np.array(
        [[0, 0], [largura - 1, 0], [largura - 1, altura - 1], [0, altura - 1]],
        dtype=np.float32,
    )
    matriz = cv2.getPerspectiveTransform(quadrilatero, destino)
    altura_quadro, largura_quadro = frame.shape[:2]
    area_quadro = float(altura_quadro * largura_quadro)
    return (
        cv2.warpPerspective(frame, matriz, (largura, altura), flags=cv2.INTER_CUBIC),
        Alinhamento(metodo=METODO_QUADRILATERO),
        # Sem homografia não há erro de reprojeção, mas o quadrilátero detectado já
        # descreve o enquadramento: é a mesma geometria por outro caminho. A matriz vai
        # para a escala canônica antes — `medir_enquadramento` raciocina em pixels
        # canônicos, e o SUPERSAMPLE inflaria o `px_por_digito` por 4.
        medir_enquadramento(
            _para_escala_canonica(matriz), frame.shape, CANON_WIDTH, CANON_HEIGHT, perfil.rois
        )
        if area_quadro > 0.0
        else Qualidade(),
    )


def _para_escala_canonica(matriz: np.ndarray) -> np.ndarray:
    """Converte uma matriz que sai no canônico AMPLIADO em uma que sai no canônico.

    Dividir a matriz inteira por SUPERSAMPLE não serviria: em coordenadas homogêneas H e
    cH descrevem a mesma transformação, então a divisão não faria nada. A escala precisa
    ser composta, e só nas duas primeiras linhas.
    """
    reducao = np.array(
        [[1.0 / SUPERSAMPLE, 0.0, 0.0], [0.0, 1.0 / SUPERSAMPLE, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    return reducao @ matriz.astype(np.float64)


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


def _align_to_template(
    frame: np.ndarray, perfil: PerfilOCR
) -> tuple[np.ndarray, Alinhamento, Qualidade] | None:
    """Casa a foto contra o gabarito e devolve o canônico ampliado, ou None se não casar.

    Junto vem o quanto o casamento é confiável. Devolver só a imagem, como antes, apagava
    a única evidência de POR QUE uma leitura saiu torta: a #28 casou com inliers suficientes
    para passar no corte e ainda assim derivou o bloco esquerdo do painel. Com o erro medido
    por campo, esse caso passa a ser visível no banco em vez de ser reconstruído à mão.

    """
    try:
        detector, kp_gabarito, des_gabarito = _get_template()
    except FileNotFoundError:
        return None

    keypoints, descritores = detector.detectAndCompute(_match_features(frame), None)
    if descritores is None or len(keypoints) < perfil.min_homography_inliers:
        return None

    pares = cv2.BFMatcher().knnMatch(descritores, des_gabarito, k=2)
    bons = [
        melhor
        for melhor, segundo in (par for par in pares if len(par) == 2)
        if melhor.distance < LOWE_RATIO * segundo.distance
    ]
    if len(bons) < perfil.min_homography_inliers:
        return None

    origem = np.float32([keypoints[m.queryIdx].pt for m in bons]).reshape(-1, 1, 2)
    destino = np.float32([kp_gabarito[m.trainIdx].pt for m in bons]).reshape(-1, 1, 2)
    homografia, mascara = cv2.findHomography(
        origem, destino, cv2.RANSAC, RANSAC_REPROJ_THRESHOLD
    )
    if homografia is None or int(mascara.sum()) < perfil.min_homography_inliers:
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
    # O espaço de casamento tem as dimensões do canônico, então os pontos do gabarito já
    # estão em coordenadas canônicas e o erro de reprojeção sai na mesma unidade das ROIs:
    # "este campo está N pixels fora do lugar" é lido direto.
    return (
        cv2.warpPerspective(
            frame,
            escala_saida @ homografia @ escala_entrada,
            (CANON_WIDTH * SUPERSAMPLE, CANON_HEIGHT * SUPERSAMPLE),
            flags=cv2.INTER_CUBIC,
        ),
        medir_alinhamento(homografia, origem, destino, mascara, perfil.rois),
        medir_enquadramento(
            homografia @ escala_entrada, frame.shape, CANON_WIDTH, CANON_HEIGHT, perfil.rois
        ),
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


@dataclass(frozen=True)
class _Resultado:
    """O que o OCR extraiu de um recorte.

    `caixa` é onde o texto vencedor estava DE FATO, no espaço canônico — não onde a ROI
    dizia que ele deveria estar. Essa diferença é o insumo do afinador de ROI: acumulada
    sobre leituras que saíram certas, ela diz para onde a região precisa andar. O easyocr
    sempre devolveu essa caixa; o código a descartava.
    """

    texto: str | None = None
    valor: float | None = None
    confianca: float | None = None
    status: str = "unreadable"
    motivo: str | None = None
    caixa: tuple[float, float, float, float] | None = None


def _caixa_canonica(
    pontos, roi: tuple[int, int, int, int]
) -> tuple[float, float, float, float]:
    """Caixa do easyocr (4 vértices, em pixels do recorte ampliado) -> espaço canônico."""
    xs = [float(ponto[0]) for ponto in pontos]
    ys = [float(ponto[1]) for ponto in pontos]
    x1, y1 = roi[0], roi[1]
    return (
        x1 + min(xs) / SUPERSAMPLE,
        y1 + min(ys) / SUPERSAMPLE,
        x1 + max(xs) / SUPERSAMPLE,
        y1 + max(ys) / SUPERSAMPLE,
    )


def _read_field(
    crop: np.ndarray, campo: Campo, perfil: PerfilOCR, roi: tuple[int, int, int, int]
) -> _Resultado:
    if crop.size == 0:
        return _Resultado(motivo="recorte vazio")

    engine = _get_ocr_engine()
    confiancas: dict[float, list[float]] = {}
    textos: dict[float, str] = {}
    caixas: dict[float, list[tuple[float, float, float, float]]] = {}

    for variante in _variants(crop):
        for pontos, texto, confianca in engine.readtext(
            variante, detail=1, paragraph=False, allowlist=OCR_ALLOWLIST
        ):
            valor, inferido = parse_valor(str(texto), campo)
            if valor is None:
                continue
            confiancas.setdefault(valor, []).append(float(confianca))
            caixas.setdefault(valor, []).append(_caixa_canonica(pontos, roi))
            if inferido:
                textos.setdefault(valor, str(texto).strip())
            else:
                # Leitura com separador descreve melhor o campo: sobrepõe a inferida.
                textos[valor] = str(texto).strip()

    if not confiancas:
        return _Resultado(motivo="nada legível no recorte")

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
    if len(votos) < perfil.min_variantes_concordando:
        motivo = "apenas uma variante da imagem leu este valor"
    elif confianca_media < perfil.min_confianca:
        motivo = f"confiança baixa ({confianca_media:.2f})"
    elif fora_da_faixa_esperada(valor, campo):
        motivo = f"fora da faixa de operação ({descrever_faixa_esperada(campo)})"
    else:
        motivo = None

    # A caixa vem da mediana entre as variantes: uma delas pode ter engolido um pixel de
    # borda, e a mediana não se move por causa disso.
    vistas = caixas[valor]
    mediana = tuple(
        sorted(canto[i] for canto in vistas)[len(vistas) // 2] for i in range(4)
    )

    return _Resultado(
        texto=textos[valor],
        valor=valor,
        confianca=confianca_media,
        status="ok" if motivo is None else "low_confidence",
        motivo=motivo,
        caixa=mediana,  # type: ignore[arg-type]
    )


@lru_cache(maxsize=1)
def _get_ocr_engine():
    # Import tardio: easyocr carrega torch e os modelos de reconhecimento. Mantendo-o
    # aqui, uma instalação incompleta falha apenas em /api/mahu/ler, e não derruba a
    # API inteira no import de routes/pontos.py.
    import easyocr

    return easyocr.Reader(["en"], gpu=False, verbose=False)
