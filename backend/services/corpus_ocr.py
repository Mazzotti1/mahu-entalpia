"""O juiz: que leituras servem de verdade, como se mede um perfil, e quando ele entra.

Puro — nem sqlite, nem OpenCV, nem pydantic. É de propósito: a regra que decide o que roda
em produção é a parte mais fácil de errar em silêncio, e a única defesa barata é poder
exercitá-la com números inventados, sem banco e sem foto.

Três decisões moram aqui.

**Nem todo rótulo vale o mesmo.** O par sugerido/aplicado é ground truth de graça, mas só
quando alguém de fato conferiu. Aplicar seis campos em um segundo e meio sem mudar nada não
é evidência de que a leitura estava certa — foi exatamente assim que a leitura #28 entrou no
banco com quatro campos corrompidos e confiança alta em todos. Tratar esse caso como verdade
ensinaria o afinador a reproduzir o erro.

**Ajustar e medir no mesmo dado sempre "melhora".** Por isso a partição é temporal e não
aleatória: o candidato é montado sobre as leituras antigas e julgado sobre as recentes, que
ele nunca viu. Partição aleatória vazaria — duas fotos do mesmo minuto são quase a mesma
foto, e cairiam uma de cada lado.

**Diferença pequena em corpus pequeno é ruído.** Com 30 leituras, um acerto a mais vira
"+3%" e parece progresso. O teste de McNemar olha só os itens em que os dois perfis
discordam e pergunta se a vantagem do candidato sobreviveria ao acaso. Sem isso, o laço
promoveria configuração aleatória com regularidade.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Tolerância de comparação: os valores voltam do navegador como texto e reaparecem como
# 11.800000000000001. A resolução do display é muito mais grossa que isso.
TOLERANCIA = 1e-6

# Abaixo disso, aplicar sem corrigir nada não é conferência. Ninguém lê seis campos em menos
# de dois segundos. É a defesa contra a leitura carimbada virar verdade no corpus.
MS_CARIMBO = 2000

# Fração mais recente do corpus reservada para julgar. Um quinto é o meio-termo entre ter
# amostra suficiente para o teste dizer alguma coisa e deixar dado suficiente para o
# afinador trabalhar.
FRACAO_TESTE = 0.2

# Abaixo disso nenhuma promoção acontece, independente do placar. Não é conservadorismo: com
# menos que isso o teste estatístico não tem poder para distinguir melhora de sorte, e
# promover assim mesmo seria decidir no ruído.
MIN_AMOSTRAS_TESTE = 30

# Probabilidade tolerada de promover por acaso.
ALPHA = 0.05

CAMADA_OURO = "ouro"
CAMADA_PRATA = "prata"


@dataclass(frozen=True)
class CampoBruto:
    """Uma linha de `leituras_ocr_campos`, antes de virar verdade ou ser descartada."""

    key: str
    pv_sugerido: float | None
    pv_aplicado: float | None
    status: str


@dataclass(frozen=True)
class LeituraBruta:
    """Uma linha de `leituras_ocr` com seus campos. O que o banco tem, sem interpretação."""

    id: int
    criado_em: str
    imagem_arquivo: str | None
    desfecho: str
    tem_aviso: bool
    ms_na_conferencia: int | None
    campos: tuple[CampoBruto, ...]


@dataclass(frozen=True)
class CampoRotulado:
    key: str
    verdade: float
    camada: str


@dataclass(frozen=True)
class LeituraRotulada:
    id: int
    criado_em: str
    imagem_arquivo: str
    campos: tuple[CampoRotulado, ...]


def rotular(leitura: LeituraBruta) -> LeituraRotulada | None:
    """Extrai a verdade de uma leitura, ou `None` quando ela não fornece nenhuma.

    Devolve `None` para:

    - leitura sem imagem — não dá para reprocessar, então não serve de teste;
    - descartada ou pendente — descarte diz que a FOTO era ruim, não qual era o valor certo;
    - aplicada em menos de `MS_CARIMBO` sem nenhuma correção — carimbo, não conferência.

    Campo corrigido à mão é ouro: o usuário digitou o valor. Os demais campos da mesma
    leitura ficam em prata — houve atenção comprovada, mas ninguém afirmou nada sobre eles.
    E quando a validação cruzada tinha reclamado e o usuário aplicou assim mesmo, a prata
    cai fora inteira: aceitar sob aviso é justamente o gesto que não confirma nada.
    """
    if not leitura.imagem_arquivo:
        return None
    if leitura.desfecho not in ("aplicada", "corrigida"):
        return None

    aplicados = [campo for campo in leitura.campos if campo.pv_aplicado is not None]
    if not aplicados:
        return None

    corrigidos = {
        campo.key
        for campo in aplicados
        if campo.pv_sugerido is None or abs(campo.pv_sugerido - campo.pv_aplicado) > TOLERANCIA
    }

    # Atenção comprovada: ou o usuário mexeu em algo, ou ficou tempo suficiente na tela.
    atento = bool(corrigidos) or (
        leitura.ms_na_conferencia is not None and leitura.ms_na_conferencia >= MS_CARIMBO
    )
    if not atento:
        return None

    prata_vale = not leitura.tem_aviso
    campos = tuple(
        CampoRotulado(
            key=campo.key,
            verdade=campo.pv_aplicado,
            camada=CAMADA_OURO if campo.key in corrigidos else CAMADA_PRATA,
        )
        for campo in aplicados
        if campo.key in corrigidos or prata_vale
    )

    return (
        LeituraRotulada(
            id=leitura.id,
            criado_em=leitura.criado_em,
            imagem_arquivo=leitura.imagem_arquivo,
            campos=campos,
        )
        if campos
        else None
    )


def particionar(
    rotuladas: list[LeituraRotulada], fracao_teste: float = FRACAO_TESTE
) -> tuple[list[LeituraRotulada], list[LeituraRotulada]]:
    """Divide em (treino, teste) por TEMPO: o teste é a fatia mais recente.

    Aleatório vazaria. Duas fotos do mesmo painel com oito minutos de diferença são quase a
    mesma imagem — separadas ao acaso, uma treina e a outra julga, e o candidato parece
    acertar o que na prática decorou. Por tempo, julgar é sempre extrapolar.
    """
    if not rotuladas:
        return [], []

    ordenadas = sorted(rotuladas, key=lambda leitura: (leitura.criado_em, leitura.id))
    # Ao menos uma leitura no teste sempre que houver mais de uma: um teste vazio faria a
    # comparação passar por omissão, que é o pior desfecho possível aqui.
    quantas = max(1, round(len(ordenadas) * fracao_teste)) if len(ordenadas) > 1 else 0
    corte = len(ordenadas) - quantas
    return ordenadas[:corte], ordenadas[corte:]


@dataclass(frozen=True)
class PlacarCampo:
    acertos: int = 0
    total: int = 0
    erros_silenciosos: int = 0


@dataclass(frozen=True)
class Placar:
    """Como um perfil se saiu sobre um conjunto de leituras.

    `certos` guarda o resultado item a item porque a comparação entre dois perfis é
    PAREADA: o que interessa não é a diferença entre duas médias, e sim em quais campos
    exatamente um acertou e o outro errou.
    """

    leituras: int = 0
    acertos: int = 0
    total: int = 0
    erros_silenciosos: int = 0
    por_campo: dict[str, PlacarCampo] = field(default_factory=dict)
    certos: dict[tuple[int, str], bool] = field(default_factory=dict)


def montar_placar(resultados: list[tuple[LeituraRotulada, dict[str, tuple[float | None, str]]]]) -> Placar:
    """Compara o que o perfil leu com a verdade. Cada resultado é `key -> (pv, status)`.

    Erro silencioso — valor errado com status `ok` — é contado à parte porque é a única
    falha que chega ao cálculo sem passar por conferência humana. Uma leitura errada que se
    declara duvidosa custa um clique; uma que se declara boa entra no banco.
    """
    por_campo: dict[str, PlacarCampo] = {}
    certos: dict[tuple[int, str], bool] = {}
    acertos = total = silenciosos = 0

    for leitura, lido in resultados:
        for campo in leitura.campos:
            pv, status = lido.get(campo.key, (None, "unreadable"))
            certo = pv is not None and abs(pv - campo.verdade) <= TOLERANCIA

            total += 1
            acertos += certo
            silencioso = not certo and status == "ok"
            silenciosos += silencioso
            certos[(leitura.id, campo.key)] = certo

            anterior = por_campo.get(campo.key, PlacarCampo())
            por_campo[campo.key] = PlacarCampo(
                acertos=anterior.acertos + certo,
                total=anterior.total + 1,
                erros_silenciosos=anterior.erros_silenciosos + silencioso,
            )

    return Placar(
        leituras=len(resultados),
        acertos=acertos,
        total=total,
        erros_silenciosos=silenciosos,
        por_campo=por_campo,
        certos=certos,
    )


def _p_binomial_unicaudal(sucessos: int, tentativas: int) -> float:
    """P(X >= sucessos) com X ~ Binomial(tentativas, 0.5).

    Meio a meio é a hipótese nula certa aqui: se os dois perfis fossem equivalentes, cada
    discordância seria uma moeda. Exato e não aproximado porque o corpus é pequeno, que é
    exatamente onde a aproximação normal do McNemar erra.
    """
    if tentativas <= 0:
        return 1.0
    cauda = sum(math.comb(tentativas, k) for k in range(sucessos, tentativas + 1))
    return cauda / (2**tentativas)


@dataclass(frozen=True)
class Decisao:
    promover: bool
    motivo: str
    # Discordâncias: `so_campeao` o campeão acertou sozinho, `so_candidato` o inverso.
    so_campeao: int = 0
    so_candidato: int = 0
    p_valor: float = 1.0
    campos_regredidos: tuple[str, ...] = ()


def decidir(
    campeao: Placar,
    candidato: Placar,
    *,
    min_amostras: int = MIN_AMOSTRAS_TESTE,
    alpha: float = ALPHA,
) -> Decisao:
    """Promove o candidato, ou diz por que não. Sem humano no meio.

    A ordem das barreiras é a ordem da importância. Erro silencioso vem primeiro e é
    absoluto: uma configuração que lê errado com status `ok` mais vezes que a atual não
    entra nem que acerte mais no agregado, porque o que ela ganha aparece na conferência e o
    que ela perde vai direto para o banco.

    A regressão por campo vem antes do agregado pelo mesmo motivo de sempre: a média esconde
    o campo que passou a errar sempre, e é justamente ele que depois vira relatório de erro.
    """
    if candidato.total < min_amostras:
        return Decisao(
            False,
            f"corpus de teste pequeno demais ({candidato.total} campos, mínimo {min_amostras})",
        )

    if candidato.erros_silenciosos > campeao.erros_silenciosos:
        return Decisao(
            False,
            f"mais erros silenciosos que o vigente "
            f"({candidato.erros_silenciosos} contra {campeao.erros_silenciosos})",
        )

    regredidos = tuple(
        sorted(
            key
            for key, placar in candidato.por_campo.items()
            if placar.acertos < campeao.por_campo.get(key, PlacarCampo()).acertos
        )
    )
    if regredidos:
        return Decisao(False, f"regressão em {', '.join(regredidos)}", campos_regredidos=regredidos)

    # Pareado: só os campos em que os dois discordaram carregam informação. Onde ambos
    # acertaram ou ambos erraram, não há o que comparar.
    so_campeao = sum(
        1 for chave, certo in campeao.certos.items() if certo and not candidato.certos.get(chave, False)
    )
    so_candidato = sum(
        1 for chave, certo in candidato.certos.items() if certo and not campeao.certos.get(chave, False)
    )
    p_valor = _p_binomial_unicaudal(so_candidato, so_campeao + so_candidato)

    if so_candidato <= so_campeao:
        return Decisao(
            False,
            "não é melhor que o vigente"
            if so_candidato or so_campeao
            else "idêntico ao vigente no conjunto de teste",
            so_campeao,
            so_candidato,
            p_valor,
        )

    if p_valor > alpha:
        return Decisao(
            False,
            f"vantagem dentro do ruído (p={p_valor:.3f}, precisa de p<={alpha})",
            so_campeao,
            so_candidato,
            p_valor,
        )

    return Decisao(
        True,
        f"melhor em {so_candidato} campos e pior em {so_campeao} (p={p_valor:.3f})",
        so_campeao,
        so_candidato,
        p_valor,
    )
