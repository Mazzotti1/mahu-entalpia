from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.services.processo import PRESSAO_MAXIMA, PRESSAO_MINIMA


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


class MahuAviso(BaseModel):
    """Incoerência entre campos, detectada depois do OCR (services/mahu_validacao.py)."""

    codigo: str
    mensagem: str
    # Campos a destacar na conferência.
    campos: list[str]


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


class MahuCamposInput(BaseModel):
    """Campos do monitor MAHU já conferidos pelo usuário."""

    mt_01: float = Field(ge=0.0, le=100.0)
    tt01: float = Field(ge=-10.0, le=60.0)
    tt04: float = Field(ge=-10.0, le=60.0)
    tt06: float = Field(ge=-10.0, le=60.0)
    mt07: float = Field(ge=0.0, le=100.0)
    tt07: float = Field(ge=-10.0, le=60.0)
    # Liga o que foi aplicado ao que tinha sido sugerido. Ausente quando os valores foram
    # digitados sem uma leitura de OCR por trás.
    leitura_id: int | None = None
