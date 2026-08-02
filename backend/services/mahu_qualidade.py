"""Cálculo das métricas de captura. Só OpenCV — nada de OCR aqui.

Separado de `mahu_ocr` de propósito: o guia de enquadramento em tempo real precisa exatamente
destes números e de nenhum dos ~20 s de OCR. Mantendo o cálculo isolado, o endpoint de
pré-voo (checar a foto ANTES de subir 5 MB) reaproveita este módulo em vez de reimplementar
as mesmas contas em JavaScript, que é onde as duas implementações começariam a divergir.

Os tipos de retorno moram em `mahu_metricas`, que é puro — ver a direção das dependências
lá.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from backend.services.mahu_metricas import Alinhamento, Ancora, Qualidade

# Nível a partir do qual um pixel conta como estourado. Display fotografado com reflexo
# satura; texto branco de painel fica bem abaixo disso.
NIVEL_ESTOURO = 250

# Quantos inliers vizinhos entram no erro local de um campo. Poucos demais e o número vira
# ruído do keypoint mais próximo; muitos demais e ele volta a ser a média global, que é
# justamente o que esconde a deriva de um bloco só.
VIZINHOS_POR_CAMPO = 12

# Até onde procurar a âncora em volta da posição esperada, em pixels canônicos. Deriva
# maior que isto não é imprecisão de alinhamento — é a homografia ter casado outra coisa,
# e aí não há o que corrigir.
RAIO_BUSCA_ANCORA = 12


def medir_ancoras(
    canonico: np.ndarray,
    gabarito: np.ndarray,
    ancoras: dict[str, tuple[int, int, int, int]],
    largura: int,
    altura: int,
    raio: int = RAIO_BUSCA_ANCORA,
) -> dict[str, Ancora]:
    """Quanto o alinhamento derivou PERTO de cada campo, casando trechos fixos do painel.

    O erro de reprojeção diz que a homografia está ruim; não diz onde nem quanto. Estas
    âncoras dizem: cada uma é um pedaço do desenho do painel — rótulo, moldura, seta — que
    é idêntico em toda foto, e achar onde ele foi parar na imagem retificada dá a deriva
    local em pixels canônicos, exatamente na unidade das ROIs.

    É a checagem direta que faltava na leitura #28. Lá a homografia casou o suficiente para
    passar no corte global e mesmo assim deslocou o bloco esquerdo do painel; as ROIs da
    esquerda passaram a recortar o lugar errado, e nada percebeu.

    Casa por correlação normalizada, e não por OCR: o painel é uma tela de software, então
    o trecho é pixel a pixel o mesmo. Ler o rótulo com o easyocr custaria mais uma passada
    do modelo por campo para responder com menos certeza.
    """
    cinza = cv2.cvtColor(canonico, cv2.COLOR_BGR2GRAY) if canonico.ndim == 3 else canonico
    if cinza.shape[1] != largura or cinza.shape[0] != altura:
        cinza = cv2.resize(cinza, (largura, altura), interpolation=cv2.INTER_AREA)

    # CLAHE nos dois lados pelo mesmo motivo do casamento SIFT: sem normalizar contraste, o
    # trecho de uma foto escura não correlaciona com o mesmo trecho do gabarito.
    equalizador = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cinza = equalizador.apply(cinza)
    gabarito = equalizador.apply(gabarito)

    medidas: dict[str, Ancora] = {}
    for key, (x1, y1, x2, y2) in ancoras.items():
        modelo = gabarito[y1:y2, x1:x2]
        janela = cinza[
            max(0, y1 - raio) : min(altura, y2 + raio),
            max(0, x1 - raio) : min(largura, x2 + raio),
        ]
        if modelo.size == 0 or janela.shape[0] < modelo.shape[0] or janela.shape[1] < modelo.shape[1]:
            continue

        mapa = cv2.matchTemplate(janela, modelo, cv2.TM_CCOEFF_NORMED)
        _, correlacao, _, canto = cv2.minMaxLoc(mapa)
        medidas[key] = Ancora(
            dx=float(canto[0] - min(x1, raio)),
            dy=float(canto[1] - min(y1, raio)),
            correlacao=round(float(correlacao), 4),
        )

    return medidas


def medir_foto(canonico: np.ndarray, largura: int, altura: int) -> tuple[float, float]:
    """Nitidez e reflexo, medidos sobre a imagem JÁ alinhada.

    Medir depois do alinhamento é o que torna os valores comparáveis entre fotos: o
    enquadramento passa a ser sempre o mesmo, então a variância do laplaciano fala de foco
    e não de distância. Sobre a foto crua, chegar mais perto do painel aumentaria a
    "nitidez" sem nada ter ficado mais nítido.
    """
    cinza = cv2.cvtColor(canonico, cv2.COLOR_BGR2GRAY) if canonico.ndim == 3 else canonico
    # O canônico vem ampliado por SUPERSAMPLE; reduzir à escala canônica deixa o número
    # independente desse fator e corta o custo do laplaciano por 16.
    if cinza.shape[1] != largura or cinza.shape[0] != altura:
        cinza = cv2.resize(cinza, (largura, altura), interpolation=cv2.INTER_AREA)

    nitidez = float(cv2.Laplacian(cinza, cv2.CV_64F).var())
    reflexo = float(np.count_nonzero(cinza >= NIVEL_ESTOURO) / cinza.size)
    return round(nitidez, 2), round(reflexo, 5)


def medir_alinhamento(
    homografia: np.ndarray,
    origem: np.ndarray,
    destino: np.ndarray,
    mascara: np.ndarray,
    rois: dict[str, tuple[int, int, int, int]],
) -> Alinhamento:
    """Erro de reprojeção global e por campo, em pixels do espaço canônico.

    O erro por campo usa os inliers vizinhos da ROI e não uma grade fixa: com grade, um
    campo perto da divisa entre células herdaria o erro da célula errada — e são os campos
    das bordas do painel os que mais sofrem com deriva.
    """
    inliers = mascara.ravel().astype(bool)
    pontos_origem = origem.reshape(-1, 2)[inliers]
    pontos_destino = destino.reshape(-1, 2)[inliers]

    if len(pontos_destino) == 0:
        return Alinhamento(metodo="homografia", inliers=0)

    projetados = cv2.perspectiveTransform(
        pontos_origem.reshape(-1, 1, 2).astype(np.float64), homografia
    ).reshape(-1, 2)
    erros = np.linalg.norm(projetados - pontos_destino, axis=1)

    erro_por_campo: dict[str, float] = {}
    for key, (x1, y1, x2, y2) in rois.items():
        centro = np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0])
        distancias = np.linalg.norm(pontos_destino - centro, axis=1)
        vizinhos = np.argsort(distancias)[: min(VIZINHOS_POR_CAMPO, len(distancias))]
        erro_por_campo[key] = round(float(erros[vizinhos].mean()), 3)

    return Alinhamento(
        metodo="homografia",
        inliers=int(inliers.sum()),
        # Mediana e não média: um punhado de inliers ruins não deve descrever o casamento
        # inteiro, que é o que o número global existe para resumir.
        erro_reproj=round(float(np.median(erros)), 3),
        erro_reproj_pior=round(max(erro_por_campo.values()), 3) if erro_por_campo else None,
        erro_por_campo=erro_por_campo,
    )


def medir_enquadramento(
    fonte_para_canonico: np.ndarray,
    forma_do_quadro: tuple[int, int],
    largura_canonica: int,
    altura_canonica: int,
    rois: dict[str, tuple[int, int, int, int]],
) -> Qualidade:
    """Enquadramento, inclinação e resolução efetiva, derivados da própria homografia.

    A ideia é desfazer o alinhamento: projetando os quatro cantos do espaço canônico de
    volta ao quadro original, sai o quadrilátero que a tela do MAHU ocupava na foto. Dele
    vem tudo — quanto do quadro ela preenchia, o quanto estava torta, e quantos pixels
    reais cada dígito tinha. Só `nitidez` e `reflexo` não saem daqui.
    """
    altura_quadro, largura_quadro = forma_do_quadro[:2]
    cantos = np.array(
        [
            [0.0, 0.0],
            [largura_canonica, 0.0],
            [largura_canonica, altura_canonica],
            [0.0, altura_canonica],
        ],
        dtype=np.float64,
    )

    try:
        canonico_para_fonte = np.linalg.inv(fonte_para_canonico)
    except np.linalg.LinAlgError:
        return Qualidade()

    quadrilatero = cv2.perspectiveTransform(
        cantos.reshape(-1, 1, 2), canonico_para_fonte
    ).reshape(-1, 2)

    area_tela = abs(float(cv2.contourArea(quadrilatero.astype(np.float32))))
    area_quadro = float(altura_quadro * largura_quadro)
    if area_tela <= 0.0 or area_quadro <= 0.0:
        return Qualidade()

    # Escala linear entre a foto e o espaço canônico. Com ela, uma altura medida em
    # pixels canônicos vira a altura que aquele mesmo traço tinha na foto original.
    escala = math.sqrt(area_tela / (largura_canonica * altura_canonica))
    altura_media_roi = sum(y2 - y1 for _, y1, _, y2 in rois.values()) / max(len(rois), 1)

    return Qualidade(
        preenchimento=round(min(area_tela / area_quadro, 1.0), 4),
        inclinacao_graus=_inclinacao(quadrilatero),
        px_por_digito=round(altura_media_roi * escala, 1),
    )


def _inclinacao(quadrilatero: np.ndarray) -> float | None:
    """Quanto a tela projetada foge de um retângulo, em graus.

    Fotografada de frente, a tela vira um retângulo e os lados opostos ficam paralelos. É
    a perspectiva — foto de lado, de baixo, de cima — que abre o ângulo entre eles, e é ela
    que a homografia tem de corrigir. Quanto mais aberto, mais trabalho para o alinhamento
    e mais borrada a reamostragem deixa os dígitos.
    """
    superior_esquerdo, superior_direito, inferior_direito, inferior_esquerdo = quadrilatero
    pares = (
        (superior_direito - superior_esquerdo, inferior_direito - inferior_esquerdo),
        (inferior_esquerdo - superior_esquerdo, inferior_direito - superior_direito),
    )

    desvios = []
    for primeiro, segundo in pares:
        norma = float(np.linalg.norm(primeiro) * np.linalg.norm(segundo))
        if norma == 0.0:
            return None
        cosseno = float(np.dot(primeiro, segundo)) / norma
        desvios.append(math.degrees(math.acos(max(-1.0, min(1.0, cosseno)))))

    return round(max(desvios), 2)
