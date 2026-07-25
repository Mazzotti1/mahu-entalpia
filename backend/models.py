from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class MahuCampoOCR(BaseModel):
    key: str
    label: str
    unidade: str
    obrigatorio: bool
    raw_text: str | None = None
    pv: float | None = None
    confidence: float | None = None
    roi: list[int]
    # ok            = variantes de pré-processamento concordaram e o valor é plausível
    # low_confidence = valor plausível, mas leitura fraca (pouca concordância ou vírgula inferida)
    # unreadable    = nada legível ou valor fora da faixa física do campo
    status: Literal["ok", "low_confidence", "unreadable"]


class MahuLeituraResponse(BaseModel):
    campos: list[MahuCampoOCR]
    missing_keys: list[str]
    # True quando algum campo obrigatório saiu como low_confidence/unreadable:
    # o frontend deve exigir conferência manual antes de calcular.
    requires_review: bool
    suggested_simulacao: SimulacaoInput | None = None


class MahuCamposInput(BaseModel):
    """Campos do monitor MAHU já conferidos pelo usuário."""

    mt_01: float = Field(ge=0.0, le=100.0)
    tt01: float = Field(ge=-10.0, le=60.0)
    tt04: float = Field(ge=-10.0, le=60.0)
    tt06: float = Field(ge=-10.0, le=60.0)
    mt07: float = Field(ge=0.0, le=100.0)
    tt07: float = Field(ge=-10.0, le=60.0)
