"""Desfaz a promoção que azedou em produção. Puro — sem banco.

O juiz decide sobre 20% do corpus, num instante. A produção é a prova real, e ela continua
depois: outra hora do dia, outra pessoa segurando o celular, outra estação. Um candidato
pode vencer o conjunto de teste com folga e mesmo assim piorar a leitura da planta.

Sem esta camada, o único jeito de descobrir isso seria alguém olhar o relatório e reverter à
mão — que é exatamente o humano no meio que o laço existe para dispensar.

A comparação aqui NÃO é a do juiz, e não pode ser. Lá as duas configurações leem as mesmas
fotos, e a comparação é pareada. Aqui cada perfil leu fotos diferentes, tiradas em momentos
diferentes, e o que resta é comparar duas proporções em amostras independentes — Fisher
exato, que é correto para as dezenas de leituras que uma planta produz por semana.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Leituras sob o perfil novo antes de julgá-lo. Abaixo disso, uma foto ruim numa
# terça-feira derrubaria uma configuração boa.
MIN_LEITURAS_JANELA = 20

# Probabilidade tolerada de reverter à toa. Mais frouxo que o alpha da promoção de
# propósito: os custos não são simétricos. Promover errado deixa o sistema pior até alguém
# perceber; reverter errado devolve a uma configuração que já funcionava.
ALPHA_REVERSAO = 0.10


@dataclass(frozen=True)
class Janela:
    """Como um perfil se saiu num período de produção."""

    perfil_id: int
    leituras: int
    campos: int
    # Campos que o usuário teve de corrigir à mão.
    corrigidos: int
    # Campos errados que o OCR declarou `ok`.
    silenciosos: int

    @property
    def taxa_erro(self) -> float:
        return self.corrigidos / self.campos if self.campos else 0.0


@dataclass(frozen=True)
class Vigilancia:
    reverter: bool
    motivo: str
    p_valor: float = 1.0


def _p_fisher_unicaudal(a: int, b: int, c: int, d: int) -> float:
    """P(observar tabela tão ou mais extrema | as duas proporções serem iguais).

    Tabela 2x2: [[a, b], [c, d]] = [[erros novo, acertos novo], [erros antigo, acertos
    antigo]]. A cauda somada é a de MAIS erros no perfil novo — é essa a hipótese que
    justifica reverter, e testar as duas caudas dobraria a chance de reverter por acaso.

    Exato e não aproximado: com 20-40 leituras por janela, o qui-quadrado erra justamente
    onde a decisão é tomada.
    """
    linha_novo = a + b
    linha_antigo = c + d
    coluna_erros = a + c
    total = linha_novo + linha_antigo
    if total == 0 or linha_novo == 0 or linha_antigo == 0:
        return 1.0

    def probabilidade(erros_novo: int) -> float:
        return (
            math.comb(linha_novo, erros_novo)
            * math.comb(linha_antigo, coluna_erros - erros_novo)
            / math.comb(total, coluna_erros)
        )

    limite = min(linha_novo, coluna_erros)
    return sum(
        probabilidade(k)
        for k in range(a, limite + 1)
        if 0 <= coluna_erros - k <= linha_antigo
    )


def avaliar_janelas(
    novo: Janela,
    anterior: Janela,
    *,
    min_leituras: int = MIN_LEITURAS_JANELA,
    alpha: float = ALPHA_REVERSAO,
) -> Vigilancia:
    """Decide se a promoção anterior precisa ser desfeita.

    Erro silencioso vem primeiro e é absoluto, como no juiz: se o perfil novo passou a ler
    errado declarando `ok` e o anterior não fazia isso, reverte sem consultar estatística.
    A diferença entre um erro que pede conferência e um que entra direto no banco não é de
    grau, e não deve ser diluída num p-valor.
    """
    if novo.leituras < min_leituras:
        return Vigilancia(
            False,
            f"janela curta demais ({novo.leituras} de {min_leituras} leituras)",
        )
    if anterior.campos == 0:
        return Vigilancia(False, "sem janela anterior para comparar")

    if novo.silenciosos > anterior.silenciosos:
        return Vigilancia(
            True,
            f"passou a produzir erro silencioso em produção "
            f"({novo.silenciosos} contra {anterior.silenciosos})",
        )

    if novo.taxa_erro <= anterior.taxa_erro:
        return Vigilancia(
            False,
            f"desempenho mantido ou melhor "
            f"({100 * novo.taxa_erro:.1f}% contra {100 * anterior.taxa_erro:.1f}% de correção)",
        )

    p_valor = _p_fisher_unicaudal(
        novo.corrigidos,
        novo.campos - novo.corrigidos,
        anterior.corrigidos,
        anterior.campos - anterior.corrigidos,
    )
    if p_valor > alpha:
        return Vigilancia(
            False,
            f"piora dentro do ruído (p={p_valor:.3f}, precisa de p<={alpha})",
            p_valor,
        )

    return Vigilancia(
        True,
        f"correção subiu de {100 * anterior.taxa_erro:.1f}% para "
        f"{100 * novo.taxa_erro:.1f}% em produção (p={p_valor:.3f})",
        p_valor,
    )
