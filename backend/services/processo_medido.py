"""A cadeia do ar montada SÓ com o que o painel mostra — a Carta Atual.

`processo.py` resolve o processo que os setpoints impõem: dado o ar de entrada, calcula
onde cada etapa tem de terminar. Este módulo faz o oposto. Não calcula alvo nenhum: pega
os números que o operador leu na tela e pergunta que caminho o ar de fato percorreu entre
eles. É por isso que as duas cartas podem discordar, e é essa discordância que o painel de
gasto térmico dividido em duas partes existe para mostrar.

Cinco estados, um por bloco de instrumentos do painel:

    TT01    ar de entrada                  TT01 + MT_01          (par que POSICIONA o ponto)
    TT_02   após o pré-aquecimento         TT_02, W da entrada   (sensível: W não muda)
    TT_04   após o pré-resfriamento        TT_04 + PID TT04 ENTALPIA (PV)
    TT_06   após a umidificação            TT_06, saturado
    TT07    insuflamento                   TT07 + MT07           (par que POSICIONA o ponto)

MT TT MAHU 2.1 e PID UMD ABS (PV) descrevem o mesmo estado que os pares TT01+MT_01 e
TT07+MT07, e por decisão do usuário NÃO posicionam ponto: ficam como conferência, em
`desvios.py`. Um estado do ar tem dois graus de liberdade e o painel oferece três medições
em cada ponta — a terceira só pode ser confirmação, ou a carta dependeria de qual
instrumento se escolheu olhar.

Campo que não veio na leitura não vira ponto inventado: o estado é omitido e a etapa liga
os vizinhos que sobraram. A carta fica mais pobre, e não errada.
"""

from __future__ import annotations

from backend.services.processo import Aviso, Etapa, Processo, Setpoints, TipoEtapa
from backend.services.psicrometria import (
    Estado,
    estado_por_ur,
    estado_saturado,
    saturado_por_w,
    umidade_absoluta_saturacao,
)

# Os rótulos são os nomes dos campos do painel, e não P1..P5: numa carta cujos pontos vêm
# todos de instrumentos, o nome do instrumento é o que permite conferir ponto por ponto
# contra a tela do MAHU.
LABEL_ENTRADA = "TT01"
LABEL_PRE_AQUECIMENTO = "TT_02"
LABEL_PRE_RESFRIAMENTO = "TT_04"
LABEL_POS_UMIDIFICACAO = "TT_06"
LABEL_FINAL = "TT07"

# Abaixo disto a diferença é ruído de arredondamento do painel (duas casas), não etapa.
_TOLERANCIA_H = 1e-3
_TOLERANCIA_W = 1e-3

# Faixa de entalpia em que uma etapa que ganha umidade ainda conta como adiabática. A
# umidificação por água troca calor com o próprio ar (decisão C), então h quase não muda;
# 0,15 kJ/kg é o que o arredondamento de duas casas dos campos de origem pode produzir
# sozinho. Acima disso, ganhar umidade e ganhar entalpia ao mesmo tempo é serpentina.
_FOLGA_ADIABATICA = 0.15


def _estado_por_tbs_e_entalpia(tbs: float, h: float, pressao_atm: float) -> tuple[Estado, bool]:
    """O estado a `tbs` com entalpia `h`, limitado à saturação.

    Devolve `(estado, foi_limitado)`. A inversão é fechada — h = 1,006·T + W·(2501 + 1,86·T)
    resolve direto em W — mas nada nela impede um W acima da saturação, e o par lido no
    painel produz exatamente isso com alguma frequência: TT_04 = 12,20 °C com o PID de
    entalpia em 36,30 kJ/kg pede 9,52 g/kg, e a 12,20 °C o ar comporta 8,85.

    Ar supersaturado não existe, então o ponto vai para cima da curva e o chamador emite o
    aviso. Preferir a temperatura à entalpia não é arbitrário: TT_04 é sonda dedicada e de
    fonte grande no painel, e o PV do PID vem do bloco de 17 px entre linhas — o recorte
    mais arriscado da tela.
    """
    w = (h - 1.006 * tbs) / (2501.0 + 1.86 * tbs) * 1000.0
    w_maximo = umidade_absoluta_saturacao(tbs, pressao_atm)
    if w > w_maximo:
        return estado_saturado(tbs, pressao_atm), True
    # Um W negativo sairia de uma entalpia baixa demais para a temperatura lida; ar seco é o
    # limite físico do outro lado.
    return Estado(tbs=tbs, w=max(w, 0.0), pressao_atm=pressao_atm), False


def _classificar(inicio: Estado, fim: Estado) -> tuple[TipoEtapa, Estado | None]:
    """Que transformação leva `inicio` a `fim`, e onde ela dobra na saturação.

    A cadeia calculada sabe o tipo de cada etapa porque foi ela quem as construiu. Aqui os
    dois estados chegam prontos, de instrumentos diferentes, e o tipo precisa ser deduzido —
    é ele que decide a cor e a trajetória na carta e em qual serpentina o kW é lançado.
    """
    delta_h = fim.entalpia - inicio.entalpia
    delta_w = fim.w - inicio.w

    if abs(delta_h) < _TOLERANCIA_H and abs(delta_w) < _TOLERANCIA_W:
        return "nula", None

    # Ganhou umidade sem ganhar calor: umidificador, e não serpentina. O teste da entalpia
    # vem antes do da temperatura porque a umidificação adiabática TAMBÉM esfria o ar, e
    # classificá-la por temperatura a chamaria de resfriamento.
    if delta_w > _TOLERANCIA_W and abs(delta_h) <= _FOLGA_ADIABATICA:
        return "umidificacao_adiabatica", None

    if delta_h > 0.0:
        # Aquecer afasta da saturação: o percurso é reto, sem joelho.
        return "aquecimento_sensivel", None

    if delta_w < -_TOLERANCIA_W:
        # Condensou. O joelho é onde o ar chegou ao orvalho e passou a seguir a curva —
        # existe só quando ele ENTROU na serpentina insaturado.
        joelho = None if inicio.saturado else saturado_por_w(inicio.w, inicio.pressao_atm)
        return "resfriamento_desumidificacao", joelho

    return "resfriamento_sensivel", None


def resolver_processo_medido(
    medidos: dict[str, float], setpoints: Setpoints
) -> Processo | None:
    """Monta a cadeia da Carta Atual a partir dos campos conferidos do painel.

    `None` quando nem o ar de entrada pôde ser posicionado: sem TT01 e MT_01 não há primeiro
    ponto, e sem primeiro ponto não há vazão mássica nem carta.
    """
    pressao = setpoints.pressao_atm
    avisos: list[Aviso] = []

    tt01, mt_01 = medidos.get("tt01"), medidos.get("mt_01")
    if tt01 is None or mt_01 is None:
        return None

    entrada = estado_por_ur(tt01, mt_01, pressao)
    pontos: dict[str, Estado] = {LABEL_ENTRADA: entrada}

    # Pré-aquecimento é sensível: a serpentina esquenta o ar sem lhe acrescentar água, então
    # o W do ponto é o da entrada e só a temperatura vem do TT_02.
    tt02 = medidos.get("tt02")
    if tt02 is not None:
        pontos[LABEL_PRE_AQUECIMENTO] = Estado(tbs=tt02, w=entrada.w, pressao_atm=pressao)

    tt04, h_pv = medidos.get("tt04"), medidos.get("tt04_entalpia_pv")
    if tt04 is not None:
        if h_pv is not None:
            estado, limitado = _estado_por_tbs_e_entalpia(tt04, h_pv, pressao)
            if limitado:
                avisos.append(
                    Aviso(
                        codigo="entalpia_supersaturada",
                        mensagem=(
                            f"TT_04 = {tt04:.2f} °C com o PID de entalpia em {h_pv:.2f} kJ/kg "
                            f"pediria mais umidade do que o ar comporta nessa temperatura "
                            f"({estado.w:.2f} g/kg é o máximo). O ponto foi colocado sobre a "
                            "curva de saturação; um dos dois instrumentos está fora."
                        ),
                    )
                )
        else:
            # Sem o PV do PID sobra uma medição só para um estado que precisa de duas. A
            # serpentina de pré-resfriamento opera abaixo do orvalho em operação normal, e é
            # essa a hipótese registrada no aviso — o ponto não é medido, é assumido.
            estado = estado_saturado(tt04, pressao)
            avisos.append(
                Aviso(
                    codigo="p_pre_resfriamento_assumido_saturado",
                    mensagem=(
                        "O PID TT04 ENTALPIA (PV) não veio nesta leitura. O ponto do TT_04 "
                        "foi posicionado supondo o ar saturado na saída da serpentina; "
                        "informe o PV para que ele venha de medição."
                    ),
                )
            )
        pontos[LABEL_PRE_RESFRIAMENTO] = estado

    # Umidificar por água leva o ar até saturar (decisão C), e é aí que TBS = TBU = TT_06.
    tt06 = medidos.get("tt06")
    if tt06 is not None:
        pontos[LABEL_POS_UMIDIFICACAO] = estado_saturado(tt06, pressao)

    tt07, mt07 = medidos.get("tt07"), medidos.get("mt07")
    if tt07 is not None and mt07 is not None:
        pontos[LABEL_FINAL] = estado_por_ur(tt07, mt07, pressao)

    etapas: list[Etapa] = []
    labels = list(pontos)
    for de, para in zip(labels, labels[1:]):
        tipo, joelho = _classificar(pontos[de], pontos[para])
        etapas.append(
            Etapa(tipo=tipo, de=de, para=para, inicio=pontos[de], fim=pontos[para], joelho=joelho)
        )

    if len(pontos) < 2:
        avisos.append(
            Aviso(
                codigo="cadeia_medida_incompleta",
                mensagem=(
                    "Só o ar de entrada pôde ser posicionado a partir do painel. Preencha "
                    "TT_02, TT_04, TT_06, TT07 e MT07 para a Carta Atual mostrar o processo."
                ),
            )
        )

    return Processo(pontos=pontos, etapas=etapas, setpoints=setpoints, avisos=avisos)
