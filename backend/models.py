from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.services.processo import PRESSAO_MAXIMA, PRESSAO_MINIMA


class LoginInput(BaseModel):
    """Credenciais do login.

    O `pattern` do username não é regra de senha nem enfeite: fecha a entrada num alfabeto
    ASCII conhecido antes que ela chegue ao banco, e é o que dá sentido ao `COLLATE NOCASE`
    da coluna, que só sabe dobrar maiúsculas de ASCII.

    O teto de 72 na senha é o limite do bcrypt — acima disso ele trunca em silêncio, e o
    hash gravado deixaria de corresponder ao que a pessoa digitou. Não há mínimo: a política
    de senha é de quem administra, não deste formulário.
    """

    username: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    senha: str = Field(min_length=1, max_length=72)


class UsuarioResponse(BaseModel):
    id: int
    username: str
    papel: str


class PontoInput(BaseModel):
    label: str = Field(min_length=1)
    tbs: float
    ur: float | None = None
    entalpia: float | None = None
    w_abs: float | None = None
    pressao_atm: float = 101325.0

    @model_validator(mode="after")
    def validate_input_source(self) -> "PontoInput":
        sources = [self.ur is not None, self.entalpia is not None, self.w_abs is not None]
        if sum(sources) != 1:
            raise ValueError("Informe exatamente uma fonte de entrada: ur, entalpia ou w_abs.")
        return self


class PontoResponse(BaseModel):
    id: int | None = None
    label: str
    tbs: float
    w: float
    ur: float
    entalpia: float
    tbu: float
    volume_especifico: float
    ponto_orvalho: float
    fonte_calculo: Literal["ur", "entalpia", "w_abs", "banco"]


class SimulacaoInput(BaseModel):
    nome: str = Field(min_length=1)
    descricao: str | None = None
    pontos: list[PontoInput] = Field(min_length=1)


class SimulacaoResponse(BaseModel):
    id: int
    nome: str
    pontos: list[PontoResponse]


class SimulacaoResumo(BaseModel):
    """Entrada da lista de histórico: o suficiente para identificar sem carregar os pontos."""

    id: int
    nome: str
    # ISO 8601 em UTC. O SQLite guarda "YYYY-MM-DD HH:MM:SS" sem fuso, e sem o sufixo Z o
    # navegador interpretaria como hora local e mostraria a leitura no horário errado.
    criado_em: str
    total_pontos: int
    # Estado do primeiro ponto, para distinguir leituras próximas na lista.
    p1_tbs: float | None = None
    p1_ur: float | None = None


class SimulacaoListaResponse(BaseModel):
    total: int
    itens: list[SimulacaoResumo]


class MahuCampoOCR(BaseModel):
    key: str
    label: str
    unidade: str
    obrigatorio: bool
    raw_text: str | None = None
    pv: float | None = None
    confidence: float | None = None
    roi: list[int]
    # ok            = variantes concordaram, confiança suficiente e valor na faixa de operação
    # low_confidence = valor fisicamente plausível, mas duvidoso: pouca concordância entre
    #                  variantes, confiança baixa, ou fora da faixa de operação do campo
    # unreadable    = nada legível ou valor fora da faixa física do campo
    status: Literal["ok", "low_confidence", "unreadable"]
    # Por que o status não é "ok", em texto exibível. `None` quando a leitura passou.
    motivo: str | None = None


class SetpointsInput(BaseModel):
    """O que a planta persegue. Decisão B: os alvos vêm daqui, não das medições."""

    # Umidade absoluta de saída, g/kg.
    w_saida: float = Field(7.30, gt=0.0, le=30.0)
    # Temperatura de insuflamento, °C.
    tbs_final: float = Field(20.0, ge=-10.0, le=60.0)
    # Entalpia alvo de P2, kJ/kg.
    entalpia_alvo: float = Field(36.20, ge=0.0, le=120.0)
    # Entalpia alvo de P2 na carta otimizada, quando P1 chega mais seco que w_saida (zonas
    # 1/2 da estratégia por região). Zonas úmidas continuam usando `entalpia_alvo` acima.
    entalpia_alvo_seco: float = Field(28.0, ge=0.0, le=120.0)
    # Vazão volumétrica medida na ENTRADA (decisão A), m³/h.
    vazao_m3h: float = Field(36575.0, gt=0.0, le=1_000_000.0)
    # Em Pa. A faixa reaproveita a do motor para não haver dois limites divergindo, e existe
    # porque a especificação original pedia "101325 kPa" — mil atmosferas.
    pressao_atm: float = Field(101325.0, ge=PRESSAO_MINIMA, le=PRESSAO_MAXIMA)


class PontoProcessoResponse(BaseModel):
    label: str
    tbs: float
    w: float
    ur: float
    entalpia: float
    tbu: float
    volume_especifico: float
    ponto_orvalho: float
    saturado: bool
    # P1 vem de TT01+MT_01, lidos/digitados no painel. P2..P5 são derivados dos setpoints
    # pela cadeia do processo (decisão B) — "calculado" mesmo quando um campo do painel
    # (TT_04, TT_06, TT07, MT07, os PIDs) existe para conferir o mesmo estado; essa
    # conferência aparece à parte, em `ProcessoResponse.desvios`.
    fonte: Literal["lido_digitado", "calculado"]


class EtapaResponse(BaseModel):
    """Uma transformação entre dois pontos, com o que ela custou.

    `tipo` é o que diz ao desenho qual trajetória traçar e à tabela em qual serpentina
    lançar o kW. `joelho` marca onde o percurso dobrou sobre a curva de saturação.
    """

    tipo: str
    de: str
    para: str
    ativa: bool
    delta_h: float
    delta_w: float
    q_kw: float
    q_sensivel_kw: float
    q_latente_kw: float
    agua_kg_h: float
    condensado_kg_h: float
    joelho: PontoProcessoResponse | None = None


class TotaisProcessoResponse(BaseModel):
    vazao_massica_kg_s: float
    q_aquecimento_kw: float
    q_refrigeracao_kw: float
    agua_umidificacao_kg_h: float
    condensado_kg_h: float


class ProcessoAviso(BaseModel):
    codigo: str
    mensagem: str


class ProcessoInput(BaseModel):
    """Ar de entrada + setpoints. Sem `setpoints`, usa os que estão gravados."""

    tbs: float = Field(ge=-10.0, le=60.0)
    ur: float = Field(gt=0.0, le=100.0)
    setpoints: SetpointsInput | None = None
    nome: str = "Processo MAHU"
    descricao: str | None = None


class ProcessoOtimizadoInput(BaseModel):
    """Ar de entrada para a carta otimizada. Sempre usa os setpoints gravados — não há
    override por requisição, porque a otimização depende deles (entalpia_alvo_seco)."""

    tbs: float = Field(ge=-10.0, le=60.0)
    ur: float = Field(gt=0.0, le=100.0)


class DesvioResponse(BaseModel):
    """Medição do painel contra o valor que o processo dos setpoints prevê.

    Existe por causa das decisões B e D: o cálculo passa a vir dos setpoints, e TT_04,
    TT_06, TT07 e MT07 deixam de definir pontos para virar verificação. Sem isto a
    informação que eles carregam se perderia.
    """

    campo: str
    ponto: str
    propriedade: str
    unidade: str
    medido: float
    calculado: float
    diferenca: float


class ProcessoResponse(BaseModel):
    id: int | None = None
    simulacao_id: int | None = None
    setpoints: SetpointsInput
    pontos: list[PontoProcessoResponse]
    etapas: list[EtapaResponse]
    totais: TotaisProcessoResponse
    avisos: list[ProcessoAviso] = []
    desvios: list[DesvioResponse] = []
    # Entalpia do setpoint de P2 menos a do PID TT04 ENTALPIA (PV) lido/digitado — o par que
    # o gráfico de gasto térmico usa no eixo Delta H. `None` quando o campo não veio nesta
    # leitura (é opcional no painel).
    delta_h_entalpia: float | None = None
    # Qual das 4 regiões da estratégia otimizada P1 ocupa (1 vermelho .. 4 azul), só
    # informativo para legenda/rótulo da carta. `None` fora da rota otimizada, ou quando P1
    # não cai em nenhuma das 4 faixas descritas.
    regiao: int | None = None


class GastoTermicoHistoricoItem(BaseModel):
    """Uma linha do histórico gasto térmico × Delta H, para o gráfico e a planilha."""

    processo_id: int
    simulacao_id: int
    criado_em: str
    q_aquecimento_kw: float
    q_refrigeracao_kw: float
    gasto_termico_kw: float
    delta_h_entalpia: float | None = None


class GastoTermicoHistoricoResponse(BaseModel):
    itens: list[GastoTermicoHistoricoItem]


class MahuAviso(BaseModel):
    """Incoerência entre campos, detectada depois do OCR (services/mahu_validacao.py)."""

    codigo: str
    mensagem: str
    # Campos a destacar na conferência.
    campos: list[str]


class MahuQualidadeResponse(BaseModel):
    """Como a foto foi tirada. Vai ao cliente para virar instrução na próxima captura.

    Tudo opcional: quando o gabarito não casa não há geometria de onde derivar
    enquadramento, e devolver zero seria mentir que a foto estava de frente.
    """

    # 'homografia' | 'quadrilatero' | 'resize', em ordem decrescente de confiabilidade.
    align_metodo: str
    align_inliers: int | None = None
    # Em pixels do espaço canônico (1200x480), o mesmo das ROIs.
    align_erro_reproj: float | None = None
    # Pior erro local entre os campos — denuncia o bloco que derivou sozinho.
    align_erro_reproj_pior: float | None = None
    nitidez: float | None = None
    reflexo: float | None = None
    preenchimento: float | None = None
    inclinacao_graus: float | None = None
    # Altura de um dígito em pixels DA FOTO ORIGINAL: a resolução que o OCR de fato teve.
    px_por_digito: float | None = None


class MahuEnquadramentoResponse(BaseModel):
    """Veredito sobre um quadro da câmera, antes de qualquer leitura.

    Uma instrução por vez, e não uma lista: o vetor pode acusar quatro problemas ao mesmo
    tempo, e mostrar os quatro não guia ninguém — vira uma lista de reclamações que a pessoa
    lê e ignora. Corrigido o pior, o próximo aparece sozinho no quadro seguinte.
    """

    pronto: bool
    # Texto exibível. `None` quando está tudo bem.
    instrucao: str | None = None
    # Identificador estável do problema, para o cliente não comparar texto.
    codigo: str | None = None
    qualidade: MahuQualidadeResponse


class MahuDesfechoInput(BaseModel):
    """O que o usuário fez com a leitura, quando não foi aplicá-la.

    Existe porque descartar é o rótulo mais forte de foto ruim que este fluxo produz, e até
    aqui ele morria no cliente.
    """

    motivo: Literal["borrada", "reflexo", "cortada", "leu_errado", "outro"] | None = None
    # Tempo com a conferência aberta. Distingue conferir de carimbar.
    ms_na_conferencia: int | None = Field(default=None, ge=0)
    # Id da leitura que substituiu esta, quando o usuário refotografou. O par
    # (tentativa ruim, tentativa boa) da mesma tela é o exemplo mais informativo que existe
    # para o modelo de qualidade: só a foto muda.
    substituida_por: int | None = None


class MahuLeituraResponse(BaseModel):
    # Identifica a leitura na telemetria; volta em MahuCamposInput.leitura_id para o
    # backend saber a quais sugestões os valores aplicados correspondem.
    id: int | None = None
    campos: list[MahuCampoOCR]
    missing_keys: list[str]
    # True quando algum campo obrigatório saiu como low_confidence/unreadable, OU quando a
    # validação cruzada achou incoerência. O segundo caso é o que pega a leitura em que
    # todos os campos parecem bons isoladamente mas não fecham entre si.
    requires_review: bool
    avisos: list[MahuAviso] = []
    # Como a foto foi tirada. `None` só nas leituras gravadas antes da migração 4.
    qualidade: MahuQualidadeResponse | None = None


class MahuCamposInput(BaseModel):
    """Campos do monitor MAHU já conferidos pelo usuário."""

    mt_01: float = Field(ge=0.0, le=100.0)
    tt01: float = Field(ge=-10.0, le=60.0)
    tt04: float = Field(ge=-10.0, le=60.0)
    tt06: float = Field(ge=-10.0, le=60.0)
    mt07: float = Field(ge=0.0, le=100.0)
    tt07: float = Field(ge=-10.0, le=60.0)
    # Opcionais porque o painel os mostra num bloco de 3 linhas com 17 px entre SP, PV e MV:
    # é o recorte mais arriscado da tela, e uma leitura que falhe neles não pode derrubar as
    # outras seis. Presentes, viram desvio contra o processo e entram no corpus como
    # qualquer outro campo — que é o que faltava para O6.4.
    umd_abs_pv: float | None = Field(default=None, ge=0.0, le=30.0)
    tt04_entalpia_pv: float | None = Field(default=None, ge=0.0, le=120.0)
    # Liga o que foi aplicado ao que tinha sido sugerido. Ausente quando os valores foram
    # digitados sem uma leitura de OCR por trás.
    leitura_id: int | None = None
    # Tempo com a conferência aberta antes de aplicar. Ver `registrar_aplicacao`: é o que
    # separa "conferiu e aceitou" de "carimbou sem olhar", e as duas coisas não podem valer
    # como o mesmo rótulo no corpus.
    ms_na_conferencia: int | None = Field(default=None, ge=0)
