"""Regressão da reconstrução da vírgula perdida pelo OCR.

Os casos de `test_virgula_perdida_*` são os dois modos de falha medidos contra as 29
leituras de produção (docs/especificacao-processo-mahu.md §7.1). Antes das casas decimais
passarem a ser por campo, o parser tratava todo campo como sendo de 2 casas e:

  - TT_04 "118" virava 1,18 — dentro da faixa física -10..60, aceito em silêncio
  - TT_06 "88" era descartado por ter menos de 3 dígitos, e o campo caía em missing_keys
"""

from __future__ import annotations

import pytest

from backend.services.mahu_campos import CAMPOS_POR_KEY
from backend.services.mahu_parse import fora_da_faixa_esperada, parse_valor

TT01 = CAMPOS_POR_KEY["tt01"]
TT04 = CAMPOS_POR_KEY["tt04"]
TT06 = CAMPOS_POR_KEY["tt06"]
MT07 = CAMPOS_POR_KEY["mt07"]


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("118", 11.8), ("124", 12.4), ("120", 12.0), ("131", 13.1)],
)
def test_virgula_perdida_em_campo_de_uma_casa_tt04(texto: str, esperado: float) -> None:
    valor, inferido = parse_valor(texto, TT04)
    assert valor == esperado
    assert inferido is True


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("88", 8.8), ("87", 8.7), ("96", 9.6), ("90", 9.0)],
)
def test_virgula_perdida_em_campo_de_uma_casa_tt06(texto: str, esperado: float) -> None:
    """Antes eram todos rejeitados: 2 dígitos < o mínimo global de 3."""
    valor, inferido = parse_valor(texto, TT06)
    assert valor == esperado
    assert inferido is True


@pytest.mark.parametrize(("texto", "esperado"), [("2027", 20.27), ("1638", 16.38)])
def test_virgula_perdida_em_campo_de_duas_casas(texto: str, esperado: float) -> None:
    valor, inferido = parse_valor(texto, TT01)
    assert valor == esperado
    assert inferido is True


@pytest.mark.parametrize(
    ("campo", "texto", "esperado"),
    [(TT04, "11,8", 11.8), (TT06, "8,8", 8.8), (TT01, "20,27", 20.27), (MT07, "48.91", 48.91)],
)
def test_virgula_visivel_e_respeitada(campo, texto: str, esperado: float) -> None:
    valor, inferido = parse_valor(texto, campo)
    assert valor == esperado
    assert inferido is False


def test_arredonda_na_resolucao_do_display() -> None:
    """Um campo de 1 casa não pode devolver 2: o painel não mostra essa precisão."""
    assert parse_valor("11.83", TT04)[0] == 11.8


def test_separador_repetido_usa_o_ultimo() -> None:
    assert parse_valor("1.2.20", TT01)[0] == 12.20


@pytest.mark.parametrize(("campo", "texto"), [(TT01, "8.8"), (TT01, "53"), (TT04, "7")])
def test_leitura_truncada_e_descartada(campo, texto: str) -> None:
    """Menos dígitos que `casas_decimais + 1` é caractere perdido, não valor."""
    assert parse_valor(texto, campo)[0] is None


@pytest.mark.parametrize(("campo", "texto"), [(TT01, "9999"), (MT07, "15000"), (TT04, "999")])
def test_fora_da_faixa_fisica_e_descartado(campo, texto: str) -> None:
    assert parse_valor(texto, campo)[0] is None


def test_texto_sem_digito_e_descartado() -> None:
    assert parse_valor("--", TT01)[0] is None
    assert parse_valor("", TT01)[0] is None


class TestFaixaEsperada:
    def test_valor_de_operacao_passa(self) -> None:
        assert not fora_da_faixa_esperada(11.8, TT04)
        assert not fora_da_faixa_esperada(20.27, TT01)

    def test_corrupcao_antiga_agora_e_sinalizada(self) -> None:
        """1,18 continua fisicamente plausível, mas não é temperatura de operação."""
        assert fora_da_faixa_esperada(1.18, TT04)

    def test_campos_corrompidos_da_leitura_28(self) -> None:
        """docs/especificacao-processo-mahu.md §7.2 — os valores que entraram no banco."""
        assert fora_da_faixa_esperada(13.50, TT01)
        assert fora_da_faixa_esperada(16.80, TT04)
        assert fora_da_faixa_esperada(54.94, CAMPOS_POR_KEY["mt_01"])
