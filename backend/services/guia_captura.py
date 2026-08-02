"""Do vetor de qualidade para uma frase na tela. Puro — sem OpenCV, sem banco.

É o fim da linha que começou na Fase 0: as métricas de captura foram gravadas para poder
correlacionar foto com erro, o corpus mostrou onde ficam os limiares, e aqui eles viram
instrução. Melhorar a leitura mexendo no OCR tem teto; melhorar a FOTO que chega não tem,
e é a alavanca que o usuário controla.

Duas decisões de desenho, ambas sobre o que NÃO fazer.

**Uma instrução por vez.** O vetor pode acusar quatro problemas ao mesmo tempo, e mostrar os
quatro não guia ninguém — vira uma lista de reclamações que a pessoa lê e ignora. As regras
estão em ordem de urgência e só a primeira que dispara aparece. Corrigido o pior, o próximo
aparece sozinho no quadro seguinte.

**Nada de nota de 0 a 100.** Uma barra de qualidade informa que está ruim e não diz o que
fazer com o celular. Cada regra aqui existe porque tem uma ação física do outro lado:
aproximar, firmar, mudar o ângulo, ficar de frente.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.services.mahu_metricas import METODO_HOMOGRAFIA, Alinhamento, Qualidade


@dataclass(frozen=True)
class LimiaresCaptura:
    """Onde fica a fronteira entre foto que lê e foto que não lê.

    Os padrões vêm da medição sobre as 9 fotos de `docs/fotosMahu`, com folga: a pior
    delas ainda lida tinha 13,3 px por dígito, erro de reprojeção 1,13 e nitidez 534. Os
    limiares ficam abaixo disso para não recusar foto que funcionaria — recusar demais
    treina o usuário a ignorar o aviso, que é pior que não avisar.

    Viram números do corpus assim que houver leituras suficientes; até lá são estes.
    """

    px_por_digito_min: float = 12.0
    nitidez_min: float = 300.0
    reflexo_max: float = 0.02
    inclinacao_max: float = 12.0
    erro_reproj_max: float = 3.0
    # Quantas leituras sustentam estes valores. 0 = ainda são os do código.
    amostras: int = 0


@dataclass(frozen=True)
class Veredito:
    """O que dizer ao usuário agora."""

    pronto: bool
    # A instrução mais urgente, ou `None` quando está tudo bem.
    instrucao: str | None = None
    # Identificador estável do problema, para o frontend não comparar texto.
    codigo: str | None = None


# Ordem = urgência. O alinhamento vem primeiro porque, sem ele, os outros números nem
# existem: não há geometria de onde derivar inclinação ou resolução.
_PRONTO = Veredito(pronto=True)


def avaliar(
    qualidade: Qualidade,
    alinhamento: Alinhamento,
    limiares: LimiaresCaptura | None = None,
) -> Veredito:
    """A instrução mais urgente para esta captura, ou 'pronto'.

    Recebe os dois objetos porque eles descrevem coisas diferentes e ambas importam aqui:
    `Qualidade` é como a foto foi tirada, `Alinhamento` é o quanto ela casou com o gabarito.
    O método de retificação domina tudo — fora de `homografia`, os outros números derivam de
    uma geometria que o próprio código não confiou o suficiente para usar.
    """
    metodo = alinhamento.metodo
    limiares = limiares or LimiaresCaptura()

    if metodo != METODO_HOMOGRAFIA:
        return Veredito(
            False,
            "Encaixe a tela inteira do MAHU dentro da moldura.",
            "sem_alinhamento",
        )

    # Resolução antes de foco: dígito pequeno demais não é salvo por nitidez nenhuma, e
    # "aproxime" é a ação mais fácil de executar segurando o celular.
    if _abaixo(qualidade.px_por_digito, limiares.px_por_digito_min):
        return Veredito(False, "Aproxime: os números estão pequenos demais.", "longe")

    if _acima(qualidade.reflexo, limiares.reflexo_max):
        return Veredito(False, "Mude o ângulo: há reflexo na tela.", "reflexo")

    if _abaixo(qualidade.nitidez, limiares.nitidez_min):
        return Veredito(False, "Firme o celular: a imagem está tremida.", "tremido")

    if _acima(qualidade.inclinacao_graus, limiares.inclinacao_max):
        return Veredito(False, "Fique de frente para a tela.", "torto")

    # Por último porque é o mais abstrato: quando os quatro anteriores passam e o
    # casamento ainda está torto, sobra centralizar. Usa o PIOR erro local e não a mediana:
    # é o bloco que derivou sozinho que estraga a leitura, e ele some numa média.
    if _acima(alinhamento.erro_reproj_pior, limiares.erro_reproj_max):
        return Veredito(False, "Centralize a tela na moldura.", "desalinhado")

    return _PRONTO


def _abaixo(valor: float | None, limiar: float) -> bool:
    """Métrica ausente não dispara aviso: falta de medida não é evidência de problema."""
    return valor is not None and valor < limiar


def _acima(valor: float | None, limiar: float) -> bool:
    return valor is not None and valor > limiar
