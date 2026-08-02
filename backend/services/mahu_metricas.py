"""Métricas de uma captura: como a foto foi tirada e quão bem ela alinhou.

Sem dependência externa nenhuma — nem OpenCV, nem pydantic. É o que permite `telemetria_ocr`
gravar essas métricas sem arrastar o cv2 para o import de `routes/pontos.py`, que é
justamente a proteção que faz uma instalação sem OpenCV falhar só em `/api/mahu/ler` em vez
de derrubar a API inteira. O cálculo mora em `mahu_qualidade` (esse sim usa cv2):

    mahu_metricas (puro) <- mahu_qualidade (OpenCV) <- mahu_ocr (OpenCV + easyocr)
    mahu_metricas (puro) <- telemetria_ocr (só sqlite)

Existem porque a telemetria hoje sabe QUE a leitura errou e não sabe POR QUÊ. A leitura #28
corrompeu quatro campos de uma vez por deriva do alinhamento, e nada no banco distingue
aquela foto de uma boa. Sem um vetor numérico por captura não há como correlacionar
"foto assim" com "leitura errada" — que é o insumo do pré-voo (O4.5) e do guia de
enquadramento na câmera.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Como a foto chegou ao espaço canônico, em ordem decrescente de confiabilidade.
METODO_HOMOGRAFIA = "homografia"
METODO_QUADRILATERO = "quadrilatero"
METODO_RESIZE = "resize"


@dataclass(frozen=True)
class Alinhamento:
    """Qualidade do casamento da foto contra o gabarito.

    `erro_por_campo` é o ponto: a #28 mostra que o casamento pode estar bom de um lado do
    painel e ruim do outro, e um número global esconde exatamente isso. O erro de cada
    campo é medido com os inliers vizinhos da ROI dele, então um campo com casamento
    localmente ruim aparece mesmo quando a mediana global está ótima.
    """

    metodo: str
    inliers: int | None = None
    # Erro de reprojeção mediano dos inliers, em pixels do espaço canônico (1200x480).
    erro_reproj: float | None = None
    # Pior erro local entre os campos — o que denuncia a deriva de um bloco só.
    erro_reproj_pior: float | None = None
    erro_por_campo: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Ancora:
    """Deriva local do alinhamento perto de um campo, medida contra o gabarito.

    `dx`/`dy` são em pixels canônicos, a mesma unidade das ROIs: "este campo está 6 px à
    direita de onde a região supõe". `correlacao` diz o quanto confiar nisso — casamento
    fraco significa que o trecho não foi encontrado, e aí a deriva medida não quer dizer nada.
    """

    dx: float
    dy: float
    correlacao: float


@dataclass(frozen=True)
class Qualidade:
    """Como a foto foi tirada. Cada campo aqui vira uma instrução na tela da câmera.

    Todos são opcionais: nos caminhos de retificação que não são a homografia não há
    geometria confiável para derivar enquadramento, e inventar número seria pior que
    admitir a ausência.
    """

    # Variância do laplaciano sobre o canônico. Medida DEPOIS do alinhamento, então o
    # enquadramento é sempre o mesmo e os valores são comparáveis entre fotos —
    # sobre a foto crua ela variaria com a distância e não diria nada sobre foco.
    # Instrução: "firme o celular".
    nitidez: float | None = None
    # Fração de pixels estourados no canônico. Instrução: "mude o ângulo, tem reflexo".
    reflexo: float | None = None
    # Área da tela no quadro original / área do quadro. Instrução: "aproxime".
    preenchimento: float | None = None
    # Desvio do paralelismo entre lados opostos da tela projetada, em graus.
    # Instrução: "fique de frente".
    inclinacao_graus: float | None = None
    # Altura de um dígito em pixels DA FOTO ORIGINAL. É a resolução que o OCR de fato
    # teve, e o motivo de a dica mandar deitar o celular. Instrução: "aproxime mais".
    px_por_digito: float | None = None


# --- Desfecho de uma leitura ------------------------------------------------------------
# O que aconteceu depois que a leitura voltou ao usuário. Hoje só existe o par
# sugerido/aplicado, e a leitura abandonada fica com `pv_aplicado` NULL para sempre —
# indistinguível de "fechou a aba". Descarte é o rótulo mais forte de foto ruim que
# existe neste fluxo, e é o que está indo para o lixo.
DESFECHO_PENDENTE = "pendente"
DESFECHO_APLICADA = "aplicada"
DESFECHO_CORRIGIDA = "corrigida"
DESFECHO_DESCARTADA = "descartada"

DESFECHOS = frozenset(
    {DESFECHO_PENDENTE, DESFECHO_APLICADA, DESFECHO_CORRIGIDA, DESFECHO_DESCARTADA}
)

# Por que o usuário jogou a leitura fora. Os três primeiros rotulam a FOTO e alimentam o
# modelo de qualidade; `leu_errado` rotula o OCR com foto boa, que é um caso diferente e
# não deve puxar os limiares de captura.
MOTIVOS_DESCARTE = frozenset({"borrada", "reflexo", "cortada", "leu_errado", "outro"})
