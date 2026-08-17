"""A CARTA OTIMIZADA: o caminho mais barato entre o ar que já está lá e o ar exigido.

Parte dos dois primeiros pontos MEDIDOS da Carta Atual — entrada (TT01+MT_01) e saída do
pré-aquecimento (TT_02) — porque esses dois já aconteceram: quando o operador tira a foto, o
ar já atravessou o pré-aquecedor. Otimizar o que é passado não economiza nada. O que ainda
está em aberto é o resto do percurso, e é só sobre ele que este módulo decide.

## Por que existe um ótimo, e qual é

O destino é fixo pelos setpoints: W = `w_saida` e TBS = `tbs_final`. Um estado do ar tem dois
graus de liberdade, então o ponto final está inteiramente determinado — não há o que escolher
lá. O que se escolhe é ONDE a serpentina fria para, e essa escolha é a `entalpia_alvo`.

Chegar a `w_saida` exige, necessariamente, tocar a curva de saturação em W = `w_saida`:
condensar é a única forma de tirar água do ar, e o ar só condensa saturado. Esse toque
acontece num ponto único — `saturado_por_w(w_saida)`, que na configuração de referência é
9,35 °C com 27,79 kJ/kg. Logo:

- parar a serpentina ANTES dele deixa o ar úmido demais, e o setpoint não é alcançado;
- parar DEPOIS dele (entalpia alvo mais baixa) resfria mais do que o necessário — e cada
  kJ a mais retirado ali precisa ser devolvido pelo reaquecimento até `tbs_final`. Paga-se
  duas vezes: no chiller e na serpentina quente.

Então o ótimo não é procurado por varredura, é deduzido: **a entalpia alvo ótima é a do ar
saturado em `w_saida`**. Qualquer outra é estritamente mais cara, e por isso não há trade-off
entre energia e dinheiro aqui — o mesmo alvo minimiza os dois, quaisquer que sejam as
tarifas. As tarifas entram só para DIZER quanto se economiza (`custos.py`), não para escolher.

O ramo úmido e o seco convergem para esse mesmo ponto, o que é o que torna a regra única:

- ar chegando mais úmido que `w_saida`: resfria condensando e para exatamente lá;
- ar chegando mais seco: resfria a W constante até a mesma entalpia e depois umidifica de
  forma adiabática (entalpia constante, decisão C), o que o leva à saturação naquela mesma
  entalpia — ou seja, ao mesmo ponto.

## O que o módulo NÃO otimiza, e denuncia

O pré-aquecimento. Ele é dado, mas quando o ar sai dele mais quente e o passo seguinte é
resfriar, cada kW entregue ali volta a ser pago no chiller. Isso não cabe num ponto da
carta, então sai como aviso, com o número na mão.
"""

from __future__ import annotations

from backend.services.custos import Tarifas
from backend.services.energia import vazao_massica_ar_seco
from backend.services.processo import (
    Aviso,
    Etapa,
    Processo,
    Setpoints,
    aquecer_sensivel_ate_tbs,
    resfriar_ate_entalpia,
    resfriar_saturado_ate_w,
    umidificar_adiabatico_ate_saturacao,
)
from backend.services.processo_medido import (
    LABEL_ENTRADA,
    LABEL_FINAL,
    LABEL_POS_UMIDIFICACAO,
    LABEL_PRE_AQUECIMENTO,
    LABEL_PRE_RESFRIAMENTO,
)
from backend.services.psicrometria import Estado, saturado_por_w

# Os rótulos são os MESMOS da Carta Atual de propósito: é o que permite a tabela de baixo
# comparar linha a linha o que cada ponto foi e o que ele poderia ter sido.


def entalpia_alvo_otima(setpoints: Setpoints) -> float:
    """A entalpia do ar saturado em `w_saida` — o ponto em que a desumidificação termina.

    É o alvo mais alto que ainda cumpre o setpoint de umidade, e por isso o mais barato:
    ver a dedução no topo do módulo.
    """
    return saturado_por_w(setpoints.w_saida, setpoints.pressao_atm).entalpia


def resolver_processo_otimizado(
    entrada: Estado,
    pre_aquecimento: Estado | None,
    setpoints: Setpoints,
    entalpia_alvo: float | None = None,
) -> Processo:
    """A rota mais barata a partir dos dois primeiros pontos medidos.

    `pre_aquecimento` é `None` quando o TT_02 não veio na leitura; aí a otimização começa na
    própria entrada, e a carta fica com um ponto a menos em vez de um ponto inventado.

    `entalpia_alvo` informado desliga a otimização e usa o alvo digitado — é o "e se" do
    campo PID TT04 ENTALPIA (SP). Vem com aviso: qualquer valor diferente do ótimo é, por
    construção, mais caro.
    """
    pressao = setpoints.pressao_atm
    avisos: list[Aviso] = []

    pontos: dict[str, Estado] = {LABEL_ENTRADA: entrada}
    etapas: list[Etapa] = []

    partida = entrada
    if pre_aquecimento is not None:
        pontos[LABEL_PRE_AQUECIMENTO] = pre_aquecimento
        etapas.append(
            Etapa(
                tipo=(
                    "aquecimento_sensivel"
                    if pre_aquecimento.entalpia > entrada.entalpia
                    else "nula"
                ),
                de=LABEL_ENTRADA,
                para=LABEL_PRE_AQUECIMENTO,
                inicio=entrada,
                fim=pre_aquecimento,
            )
        )
        partida = pre_aquecimento

    h_otimo = entalpia_alvo_otima(setpoints)
    h_alvo = h_otimo if entalpia_alvo is None else entalpia_alvo
    if entalpia_alvo is not None and abs(entalpia_alvo - h_otimo) > 0.01:
        avisos.append(
            Aviso(
                codigo="alvo_digitado_acima_do_otimo",
                mensagem=(
                    f"Esta carta está usando o alvo digitado de {entalpia_alvo:.2f} kJ/kg. O "
                    f"ótimo para o setpoint de {setpoints.w_saida:.2f} g/kg é "
                    f"{h_otimo:.2f} kJ/kg — qualquer outro valor custa mais, porque ou não "
                    "alcança a umidade exigida, ou resfria além do necessário e o "
                    "reaquecimento devolve a diferença. Limpe o campo para voltar ao ótimo."
                ),
            )
        )

    # Serpentina fria: para exatamente na entalpia ótima. O joelho marca onde o percurso
    # encontrou a saturação e passou a segui-la.
    pre_resfriamento, joelho = resfriar_ate_entalpia(partida, h_alvo)
    pontos[LABEL_PRE_RESFRIAMENTO] = pre_resfriamento
    etapas.append(
        Etapa(
            tipo=(
                "aquecimento_sensivel"
                if pre_resfriamento.entalpia > partida.entalpia
                else "resfriamento_desumidificacao"
                if joelho is not None
                else "resfriamento_sensivel"
            ),
            de=LABEL_PRE_AQUECIMENTO if pre_aquecimento is not None else LABEL_ENTRADA,
            para=LABEL_PRE_RESFRIAMENTO,
            inicio=partida,
            fim=pre_resfriamento,
            joelho=joelho,
        )
    )

    # Umidificar só se o ar ainda estiver mais seco que o setpoint. Na rota ótima essa etapa
    # o leva à saturação na MESMA entalpia, que é o ponto de saída — nunca há over-shoot.
    # A folga não é decorativa: na rota ótima o resfriamento PARA na saturação em `w_saida`,
    # e a inversão numérica devolve 7,2999... Sem tolerância isso dispara uma umidificação de
    # comprimento zero, que entra na legenda da carta como uma etapa que não existe.
    if pre_resfriamento.w < setpoints.w_saida - 1e-6:
        pos_umidificacao = umidificar_adiabatico_ate_saturacao(pre_resfriamento)
        etapas.append(
            Etapa(
                tipo="umidificacao_adiabatica",
                de=LABEL_PRE_RESFRIAMENTO,
                para=LABEL_POS_UMIDIFICACAO,
                inicio=pre_resfriamento,
                fim=pos_umidificacao,
            )
        )
    else:
        # O ponto continua existindo para as duas cartas terem as mesmas linhas na tabela;
        # a etapa é nula porque nada acontece nela.
        pos_umidificacao = resfriar_saturado_ate_w(pre_resfriamento, setpoints.w_saida)
        etapas.append(
            Etapa(
                tipo="nula" if pos_umidificacao.w >= pre_resfriamento.w else "resfriamento_desumidificacao",
                de=LABEL_PRE_RESFRIAMENTO,
                para=LABEL_POS_UMIDIFICACAO,
                inicio=pre_resfriamento,
                fim=pos_umidificacao,
            )
        )
    pontos[LABEL_POS_UMIDIFICACAO] = pos_umidificacao

    final = aquecer_sensivel_ate_tbs(pos_umidificacao, setpoints.tbs_final)
    pontos[LABEL_FINAL] = final
    etapas.append(
        Etapa(
            tipo="aquecimento_sensivel" if final.tbs > pos_umidificacao.tbs else "nula",
            de=LABEL_POS_UMIDIFICACAO,
            para=LABEL_FINAL,
            inicio=pos_umidificacao,
            fim=final,
        )
    )

    _avisar_sobre_pre_aquecimento(entrada, pre_aquecimento, setpoints, avisos)

    return Processo(pontos=pontos, etapas=etapas, setpoints=setpoints, avisos=avisos)


def _avisar_sobre_pre_aquecimento(
    entrada: Estado,
    pre_aquecimento: Estado | None,
    setpoints: Setpoints,
    avisos: list[Aviso],
) -> None:
    """Aquecer antes de resfriar é pago duas vezes, e o número disso não cabe na carta.

    A rota ótima não pode desligar o pré-aquecedor — ele já operou quando a foto foi tirada,
    e os dois primeiros pontos são dados. Mas o custo dele é a maior economia disponível
    nesta planta e some da comparação se ninguém o disser em voz alta.
    """
    if pre_aquecimento is None or pre_aquecimento.entalpia <= entrada.entalpia:
        return

    vazao_kg_s = vazao_massica_ar_seco(setpoints.vazao_m3h, entrada)
    q_kw = vazao_kg_s * (pre_aquecimento.entalpia - entrada.entalpia)
    avisos.append(
        Aviso(
            codigo="pre_aquecimento_pago_duas_vezes",
            mensagem=(
                f"O pré-aquecimento entregou {q_kw:.1f} kW ao ar ({entrada.tbs:.2f} °C para "
                f"{pre_aquecimento.tbs:.2f} °C), e a etapa seguinte é resfriar. Esses "
                f"{q_kw:.1f} kW são pagos na serpentina quente e retirados de novo no "
                "chiller. Se a umidade de entrada não exigir o pré-aquecimento, desligá-lo "
                "é a economia mais direta disponível — e ela está fora do alcance desta "
                "carta, que parte dos dois primeiros pontos já medidos."
            ),
        )
    )


def custo_evitavel_pre_aquecimento(
    entrada: Estado, pre_aquecimento: Estado | None, setpoints: Setpoints, tarifas: Tarifas
) -> float:
    """R$/h que o pré-aquecimento custa somando serpentina quente e chiller.

    Separado do aviso porque é número, e número vai para a tabela de comparação.
    """
    if pre_aquecimento is None or pre_aquecimento.entalpia <= entrada.entalpia:
        return 0.0

    vazao_kg_s = vazao_massica_ar_seco(setpoints.vazao_m3h, entrada)
    q_kw = vazao_kg_s * (pre_aquecimento.entalpia - entrada.entalpia)

    cop = tarifas.cop_refrigeracao if tarifas.cop_refrigeracao > 0 else 1.0
    rendimento = tarifas.rendimento_aquecimento if tarifas.rendimento_aquecimento > 0 else 1.0
    return (q_kw / rendimento + q_kw / cop) * tarifas.preco_kwh
