"""Monta um perfil candidato a partir do corpus. Puro — sem banco, sem foto.

Cada afinador olha um parâmetro e responde uma pergunta só: "o que os dados dizem que este
número deveria ser?". Nenhum deles decide nada. Quem decide é `corpus_ocr.decidir`, sobre a
fatia de teste que estes nunca viram — e é essa separação que impede o sistema de se
convencer sozinho.

Três regras valem para todos:

**Volume antes de opinião.** Cada parâmetro tem um mínimo de amostras abaixo do qual o
afinador se cala. Não é conservadorismo: com meia dúzia de leituras, o quantil de uma faixa
é o valor de uma leitura específica, e propor isso seria copiar ruído com cara de estatística.

**Nunca contradizer o que já foi observado.** Uma faixa proposta jamais pode excluir um
valor que a planta de fato produziu, e uma ROI jamais pode cortar um texto que o OCR de fato
leu certo ali. Sem essa trava, o afinador estreita a cada ciclo até só aceitar a média.

**Passo limitado.** As ROIs andam no máximo alguns pixels por ciclo. Uma correção grande de
uma vez, mesmo estatisticamente justificada, é indistinguível de um erro grande de uma vez —
e o segundo caso precisa de um ciclo para ser percebido e revertido.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.services.guia_captura import LimiaresCaptura
from backend.services.perfil_ocr import PerfilOCR

# --- Mínimos por parâmetro --------------------------------------------------------------
# Cada um responde a uma pergunta diferente, e por isso precisa de uma quantidade diferente
# de evidência. Uma faixa é um quantil de cauda e pede muitas leituras; uma ROI é uma média
# de posições e converge bem mais rápido.
MIN_AMOSTRAS_FAIXA = 100
MIN_AMOSTRAS_CASAS = 60
MIN_AMOSTRAS_CONFIANCA = 120
MIN_AMOSTRAS_INLIERS = 80
MIN_AMOSTRAS_ROI = 40
# Limiares de captura: cada um é um percentil de cauda, e cauda precisa de amostra.
MIN_AMOSTRAS_CAPTURA = 50

# Folga sobre o observado, como fração da amplitude. A faixa existe para separar "dígito
# trocado" de "condição incomum de planta"; apertada demais, ela transforma toda manhã fria
# em pedido de conferência.
FOLGA_FAIXA = 0.15
# Caudas descartadas antes de aplicar a folga: uma leitura conferida ainda pode estar errada.
QUANTIL_FAIXA = 0.02

# Margem em torno do texto observado, em pixels canônicos. Mesma que foi usada para medir as
# ROIs originais à mão.
MARGEM_ROI = 3.0
# Quanto uma aresta de ROI pode andar por ciclo.
DERIVA_MAX_ROI = 4.0
# Distância, em pixels canônicos, para considerar que o texto está encostado na borda do
# recorte — ou seja, que a região provavelmente está cortando o número.
TOLERANCIA_BORDA = 1.5

# Grade de limiares de confiança testados. Mais fino que isso é ilusão de precisão: a
# confiança do easyocr não é calibrada.
PASSO_CONFIANCA = 0.05


@dataclass(frozen=True)
class Proposta:
    """Uma mudança sugerida, com o número que a sustenta."""

    parametro: str
    descricao: str
    amostras: int


@dataclass(frozen=True)
class Candidato:
    perfil: PerfilOCR
    propostas: tuple[Proposta, ...]
    # Parâmetros que o afinador deixou como estão, e por quê. Explicitar é o que evita a
    # leitura de que "nada mudou porque está tudo ótimo".
    silenciados: tuple[str, ...]

    @property
    def mudou(self) -> bool:
        return bool(self.propostas)


@dataclass(frozen=True)
class ObservacaoCampo:
    """Um campo lido no treino, com o que se sabe sobre ele depois."""

    key: str
    pv_aplicado: float
    confianca: float | None
    status: str
    certo: bool


@dataclass(frozen=True)
class CaixaObservada:
    """Onde o texto apareceu num campo, e se aquela leitura saiu certa.

    As duas informações servem a propósitos opostos e por isso andam juntas. Caixa de
    leitura CERTA diz onde o texto está — é a evidência positiva. Caixa de leitura ERRADA
    encostada na borda do recorte diz que a região está cortando o texto — é a única
    evidência disponível justamente no caso em que nenhuma leitura sai certa.
    """

    caixa: tuple[float, float, float, float]
    certo: bool


@dataclass(frozen=True)
class ObservacaoLeitura:
    """Uma leitura do treino, do ponto de vista do alinhamento."""

    inliers: int | None
    # Houve ao menos um campo que o OCR errou nesta leitura.
    teve_erro: bool


def _quantil(ordenados: list[float], fracao: float) -> float:
    """Quantil por interpolação linear. Sem numpy: este módulo é importado sem OpenCV."""
    if len(ordenados) == 1:
        return ordenados[0]
    posicao = fracao * (len(ordenados) - 1)
    abaixo = int(posicao)
    acima = min(abaixo + 1, len(ordenados) - 1)
    peso = posicao - abaixo
    return ordenados[abaixo] * (1 - peso) + ordenados[acima] * peso


def afinar_faixas(
    valores: dict[str, list[float]], perfil: PerfilOCR
) -> tuple[dict[str, tuple[float, float]], list[Proposta], list[str]]:
    """Faixa de operação por campo, a partir dos valores que a planta de fato produziu.

    As faixas do código vieram de 29 leituras de julho com folga de ~20% e valem para
    aquela estação. Recalculá-las do corpus é o que faz uma troca de estação deixar de
    exigir alguém editando variável de ambiente.

    A faixa proposta nunca é mais estreita que o observado: os quantis cortam a cauda, mas
    a checagem seguinte devolve o mínimo e o máximo reais para dentro. Sem isso, cada ciclo
    apertaria em cima do anterior até a faixa virar a média.
    """
    faixas: dict[str, tuple[float, float]] = {}
    propostas: list[Proposta] = []
    silenciados: list[str] = []
    atuais = {campo.key: campo.esperada for campo in perfil.campos()}

    for key, amostras in sorted(valores.items()):
        if len(amostras) < MIN_AMOSTRAS_FAIXA:
            silenciados.append(f"faixa de {key}: {len(amostras)} de {MIN_AMOSTRAS_FAIXA} leituras")
            continue

        ordenados = sorted(amostras)
        baixo = _quantil(ordenados, QUANTIL_FAIXA)
        alto = _quantil(ordenados, 1 - QUANTIL_FAIXA)
        folga = max((alto - baixo) * FOLGA_FAIXA, 0.1)
        nova = (
            min(baixo - folga, ordenados[0]),
            max(alto + folga, ordenados[-1]),
        )
        nova = (round(nova[0], 2), round(nova[1], 2))

        if nova != atuais.get(key):
            faixas[key] = nova
            propostas.append(
                Proposta(
                    f"faixa de {key}",
                    f"{atuais.get(key)} -> {nova}",
                    len(amostras),
                )
            )

    return faixas, propostas, silenciados


def afinar_casas_decimais(
    valores: dict[str, list[float]], perfil: PerfilOCR
) -> tuple[dict[str, int], list[Proposta], list[str]]:
    """Quantas casas o display mostra em cada campo, medido pelos valores aplicados.

    Este é o parâmetro que produziu erro silencioso em produção: `casas_decimais` era global
    e TT_04 e TT_06 mostram uma casa a menos, o que fazia a reconstrução da vírgula deslocar
    o valor. Ver docs/especificacao-processo-mahu.md §7.1.

    Só propõe REDUZIR, e só quando a última casa é zero em todas as amostras. Aumentar
    exigiria ver um dígito que o display não mostra, e a única forma de isso aparecer nos
    dados é o OCR ter lido lixo — exatamente o que não pode virar configuração.
    """
    casas: dict[str, int] = {}
    propostas: list[Proposta] = []
    silenciados: list[str] = []

    for campo in perfil.campos():
        amostras = valores.get(campo.key, [])
        if len(amostras) < MIN_AMOSTRAS_CASAS:
            silenciados.append(
                f"casas de {campo.key}: {len(amostras)} de {MIN_AMOSTRAS_CASAS} leituras"
            )
            continue
        if campo.casas_decimais <= 0:
            continue

        # Última casa sempre zero => o display mostra uma casa a menos do que se supõe.
        escala = 10 ** (campo.casas_decimais - 1)
        redundante = all(abs(valor * escala - round(valor * escala)) < 1e-9 for valor in amostras)
        if not redundante:
            continue

        casas[campo.key] = campo.casas_decimais - 1
        propostas.append(
            Proposta(
                f"casas de {campo.key}",
                f"{campo.casas_decimais} -> {campo.casas_decimais - 1}"
                " (última casa foi zero em todas as leituras)",
                len(amostras),
            )
        )

    return casas, propostas, silenciados


def afinar_confianca(
    observacoes: list[ObservacaoCampo], perfil: PerfilOCR
) -> tuple[float | None, list[Proposta], list[str]]:
    """Confiança mínima para uma leitura valer como `ok`.

    O limiar é uma troca: subir manda mais leitura boa para conferência, descer deixa mais
    leitura ruim entrar direto no cálculo. Os dois custos não são iguais — a conferência
    custa um clique, o erro silencioso entra no banco — então a busca minimiza silenciosos
    primeiro e só usa a taxa de conferência para desempatar.
    """
    com_confianca = [o for o in observacoes if o.confianca is not None]
    if len(com_confianca) < MIN_AMOSTRAS_CONFIANCA:
        return None, [], [
            f"confiança mínima: {len(com_confianca)} de {MIN_AMOSTRAS_CONFIANCA} campos"
        ]

    melhor: tuple[int, int, float] | None = None
    candidato = 0.30
    while candidato <= 0.90 + 1e-9:
        # Com este limiar, quais leituras teriam saído como `ok`?
        silenciosos = sum(
            1 for o in com_confianca if not o.certo and o.confianca >= candidato
        )
        conferencias = sum(1 for o in com_confianca if o.confianca < candidato)
        pontuacao = (silenciosos, conferencias, candidato)
        if melhor is None or pontuacao < melhor:
            melhor = pontuacao
        candidato = round(candidato + PASSO_CONFIANCA, 2)

    silenciosos, conferencias, limiar = melhor
    if abs(limiar - perfil.min_confianca) < 1e-9:
        return None, [], []

    return (
        limiar,
        [
            Proposta(
                "confiança mínima",
                f"{perfil.min_confianca} -> {limiar} "
                f"({silenciosos} silenciosos, {conferencias} conferências no treino)",
                len(com_confianca),
            )
        ],
        [],
    )


def afinar_min_inliers(
    observacoes: list[ObservacaoLeitura], perfil: PerfilOCR
) -> tuple[int | None, list[Proposta], list[str]]:
    """Inliers mínimos para confiar na homografia.

    O 25 do código foi escolhido sem medir, e foi suficiente para deixar a leitura #28
    passar. O corpus responde melhor: onde ficam os inliers das leituras que saíram CERTAS?
    Abaixo desse piso, casar com o gabarito não vem produzindo leitura boa, e cair para a
    retificação por quadrilátero é menos ruim que confiar numa homografia frouxa.

    Só sobe, nunca desce. Baixar o piso a partir dos dados seria pedir ao corpus permissão
    para aceitar alinhamento pior — e as leituras ruins que justificariam isso são
    justamente as que o corpus não contém, porque foram descartadas.
    """
    corretas = [o.inliers for o in observacoes if not o.teve_erro and o.inliers is not None]
    if len(corretas) < MIN_AMOSTRAS_INLIERS:
        return None, [], [f"inliers mínimos: {len(corretas)} de {MIN_AMOSTRAS_INLIERS} leituras"]

    piso = int(_quantil(sorted(float(v) for v in corretas), 0.05))
    if piso <= perfil.min_homography_inliers:
        return None, [], []

    return (
        piso,
        [
            Proposta(
                "inliers mínimos",
                f"{perfil.min_homography_inliers} -> {piso} "
                f"(percentil 5 das leituras corretas)",
                len(corretas),
            )
        ],
        [],
    )


def _sobreposta(
    proposta: tuple[int, int, int, int],
    key: str | None,
    atuais: dict[str, tuple[int, int, int, int]],
    ja_propostas: dict[str, tuple[int, int, int, int]],
) -> str | None:
    """Nome da primeira região que a proposta invadiria, ou `None`.

    Compara contra as regiões já propostas neste ciclo, e não só contra as vigentes: sem
    isso, dois campos vizinhos poderiam crescer um em direção ao outro na mesma corrida e
    passar os dois, cada um checando contra a posição antiga do outro.

    `key=None` quando não há região própria a ignorar — é o caso das âncoras, em que a do
    próprio campo também é proibida: uma ROI sobre a sua âncora é o pior caso de todos.
    """
    for outra_key in atuais:
        if outra_key == key:
            continue
        outra = ja_propostas.get(outra_key, atuais[outra_key])
        if (
            proposta[0] < outra[2]
            and outra[0] < proposta[2]
            and proposta[1] < outra[3]
            and outra[1] < proposta[3]
        ):
            return outra_key
    return None


def afinar_rois(
    caixas: dict[str, list[CaixaObservada]], perfil: PerfilOCR
) -> tuple[dict[str, tuple[int, int, int, int]], list[Proposta], list[str]]:
    """Onde cada ROI deveria estar, dado onde o texto de fato apareceu.

    As ROIs do código foram medidas à mão sobre 9 fotos alinhadas, com 3 px de margem. Com o
    corpus, a mesma medição passa a usar centenas — e, o que importa mais, passa a se
    corrigir quando o gabarito, a câmera ou o próprio painel mudam de leve.

    Duas evidências, porque uma só não resolve o caso que importa:

    **Leituras certas** definem o envelope: a região passa a envolver tudo que já foi lido
    corretamente, mais a margem. É a correção fina.

    **Texto encostado na borda** empurra aquela aresta para fora. Sem isso o afinador seria
    inútil exatamente onde é mais necessário: um campo cuja ROI está deslocada erra SEMPRE,
    nunca produz leitura certa, e ficaria para sempre sem evidência positiva — travado no
    erro que a ROI causou. Texto que toca a borda do recorte é o sinal de que a região está
    cortando o número, e ele existe justamente nesse caso.

    Cada aresta anda no máximo `DERIVA_MAX_ROI` por ciclo. Uma correção grande de uma vez é
    indistinguível de um erro grande de uma vez, e o segundo caso precisa de um ciclo para
    ser percebido e revertido pelo juiz.
    """
    novas: dict[str, tuple[int, int, int, int]] = {}
    propostas: list[Proposta] = []
    silenciados: list[str] = []

    for key, atual in sorted(perfil.rois.items()):
        observadas = caixas.get(key, [])
        if len(observadas) < MIN_AMOSTRAS_ROI:
            silenciados.append(f"ROI de {key}: {len(observadas)} de {MIN_AMOSTRAS_ROI} leituras")
            continue

        certas = [o.caixa for o in observadas if o.certo]
        if certas:
            envelope = [
                min(caixa[0] for caixa in certas) - MARGEM_ROI,
                min(caixa[1] for caixa in certas) - MARGEM_ROI,
                max(caixa[2] for caixa in certas) + MARGEM_ROI,
                max(caixa[3] for caixa in certas) + MARGEM_ROI,
            ]
        else:
            envelope = [float(coordenada) for coordenada in atual]

        # Aresta que o texto vem tocando na maioria das leituras está cortando o número.
        # A caixa não diz quanto sobrou do lado de fora — só que sobrou — então o passo é
        # o máximo permitido, e o ciclo seguinte mede de novo.
        for i, sinal in ((0, -1), (1, -1), (2, 1), (3, 1)):
            encostadas = sum(
                1 for o in observadas if abs(o.caixa[i] - atual[i]) <= TOLERANCIA_BORDA
            )
            if encostadas * 2 >= len(observadas):
                empurrada = atual[i] + sinal * DERIVA_MAX_ROI
                envelope[i] = min(envelope[i], empurrada) if sinal < 0 else max(envelope[i], empurrada)

        limitada = tuple(
            int(round(max(atual[i] - DERIVA_MAX_ROI, min(atual[i] + DERIVA_MAX_ROI, envelope[i]))))
            for i in range(4)
        )

        # Degenerada é sinal de que as caixas não descrevem o campo: melhor não mexer.
        if limitada[2] <= limitada[0] or limitada[3] <= limitada[1]:
            silenciados.append(f"ROI de {key}: caixas observadas não formam região válida")
            continue

        # Duas ROIs sobrepostas é o modo de falha que o painel oferece de graça: o bloco
        # SP/PV/MV tem 17 px entre linhas, e uma região que cresce alguns pixels por ciclo
        # acaba enxergando o setpoint da linha vizinha. Quando isso acontece, o valor lido
        # é plausível e está na faixa — ninguém percebe. A trava é geométrica porque os
        # dados não conseguem denunciar esse caso: a leitura errada parece certa.
        vizinha = _sobreposta(limitada, key, perfil.rois, novas)
        if vizinha:
            silenciados.append(f"ROI de {key}: cresceria sobre a de {vizinha}")
            continue

        # A ROI também não pode invadir âncora nenhuma. Âncora existe para medir deriva a
        # partir de um trecho FIXO do painel; contendo um número, ela passaria a medir o
        # número mudando — e a deriva inventada seria aplicada de volta à própria ROI. Esta
        # trava é o que impede o afinador de estragar a checagem que o vigia.
        invadida = _sobreposta(limitada, None, perfil.ancoras, {})
        if invadida:
            silenciados.append(f"ROI de {key}: cresceria sobre a âncora de {invadida}")
            continue

        if limitada != tuple(atual):
            novas[key] = limitada  # type: ignore[assignment]
            propostas.append(
                Proposta(f"ROI de {key}", f"{tuple(atual)} -> {limitada}", len(observadas))
            )

    return novas, propostas, silenciados


@dataclass(frozen=True)
class ObservacaoCaptura:
    """Como uma foto de produção chegou, e se ela deu certo."""

    px_por_digito: float | None
    nitidez: float | None
    reflexo: float | None
    inclinacao_graus: float | None
    erro_reproj_pior: float | None
    # Aplicada ou corrigida sem nenhum erro silencioso: a foto serviu.
    boa: bool


def afinar_limiares_captura(
    observacoes: list[ObservacaoCaptura], atuais: LimiaresCaptura
) -> tuple[LimiaresCaptura | None, list[Proposta], list[str]]:
    """Onde fica a fronteira entre foto que lê e foto que não lê, medida em produção.

    Os limiares do código vieram das 9 fotos de `docs/fotosMahu` — todas tiradas pela mesma
    pessoa, no mesmo dia, com o mesmo celular. Produção tem turno da noite, vidro sujo e
    aparelho de outra pessoa, e é ela que precisa definir o corte.

    Cada limiar é o percentil 5 das fotos que DERAM CERTO: por construção, ele recusa uma em
    cada vinte fotos que teriam funcionado. Esse erro é aceitável de propósito — o custo é
    um reenquadramento de dois segundos, enquanto deixar passar custa upload, OCR e
    conferência para terminar em descarte.

    Não passa pelo juiz, e não poderia: ele mede acerto sobre fotos já tiradas, e mudar o
    guia não altera nenhuma delas. O que valida estes números é a taxa de descarte das
    fotos que chegarem DEPOIS.
    """
    boas = [o for o in observacoes if o.boa]
    if len(boas) < MIN_AMOSTRAS_CAPTURA:
        return None, [], [
            f"limiares de captura: {len(boas)} de {MIN_AMOSTRAS_CAPTURA} fotos boas"
        ]

    def piso(extrair) -> float | None:
        valores = sorted(v for v in (extrair(o) for o in boas) if v is not None)
        return _quantil(valores, 0.05) if len(valores) >= MIN_AMOSTRAS_CAPTURA else None

    def teto(extrair) -> float | None:
        valores = sorted(v for v in (extrair(o) for o in boas) if v is not None)
        return _quantil(valores, 0.95) if len(valores) >= MIN_AMOSTRAS_CAPTURA else None

    novos = LimiaresCaptura(
        px_por_digito_min=_ou(piso(lambda o: o.px_por_digito), atuais.px_por_digito_min),
        nitidez_min=_ou(piso(lambda o: o.nitidez), atuais.nitidez_min),
        reflexo_max=_ou(teto(lambda o: o.reflexo), atuais.reflexo_max),
        inclinacao_max=_ou(teto(lambda o: o.inclinacao_graus), atuais.inclinacao_max),
        erro_reproj_max=_ou(teto(lambda o: o.erro_reproj_pior), atuais.erro_reproj_max),
        amostras=len(boas),
    )

    return (
        novos,
        [
            Proposta(
                "limiares de captura",
                f"px/dígito ≥ {novos.px_por_digito_min:.1f}, nitidez ≥ {novos.nitidez_min:.0f}, "
                f"reflexo ≤ {novos.reflexo_max:.4f}, inclinação ≤ {novos.inclinacao_max:.1f}°, "
                f"reprojeção ≤ {novos.erro_reproj_max:.2f}",
                len(boas),
            )
        ],
        [],
    )


def _ou(valor: float | None, padrao: float) -> float:
    return padrao if valor is None else round(valor, 4)


def montar_candidato(
    perfil: PerfilOCR,
    *,
    valores: dict[str, list[float]],
    campos: list[ObservacaoCampo],
    leituras: list[ObservacaoLeitura],
    caixas: dict[str, list[CaixaObservada]],
) -> Candidato:
    """Roda todos os afinadores e devolve um perfil só, com o que cada um propôs.

    Todos os ajustes vão juntos num candidato só, e não um por vez. É o juiz que decide, e
    ele decide sobre o conjunto: promover parâmetro a parâmetro multiplicaria as corridas
    (cada uma relê o corpus inteiro) e, pior, faria cada teste estatístico ser feito de novo
    sobre o mesmo conjunto de teste — que é como se acaba promovendo ruído por insistência.
    """
    propostas: list[Proposta] = []
    silenciados: list[str] = []

    faixas, p, s = afinar_faixas(valores, perfil)
    propostas += p
    silenciados += s

    casas, p, s = afinar_casas_decimais(valores, perfil)
    propostas += p
    silenciados += s

    confianca, p, s = afinar_confianca(campos, perfil)
    propostas += p
    silenciados += s

    inliers, p, s = afinar_min_inliers(leituras, perfil)
    propostas += p
    silenciados += s

    rois, p, s = afinar_rois(caixas, perfil)
    propostas += p
    silenciados += s

    candidato = replace(
        perfil,
        id=None,
        rois={**perfil.rois, **rois},
        faixas_esperadas={**perfil.faixas_esperadas, **faixas},
        casas_decimais={**perfil.casas_decimais, **casas},
        min_confianca=confianca if confianca is not None else perfil.min_confianca,
        min_homography_inliers=(
            inliers if inliers is not None else perfil.min_homography_inliers
        ),
    )

    return Candidato(
        perfil=candidato,
        propostas=tuple(propostas),
        silenciados=tuple(silenciados),
    )
