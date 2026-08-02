from __future__ import annotations

import pytest

from backend.services.mahu_campos import (
    CAMPOS,
    CAMPOS_OBRIGATORIOS,
    CAMPOS_POR_KEY,
    ENV_FAIXAS_ESPERADAS,
    Campo,
    aplicar_faixas_do_ambiente,
)

BASE = [
    Campo("tt01", "TT01", "°C", 2, (-10.0, 60.0), (14.0, 24.0), True),
    Campo("tt04", "TT_04", "°C", 1, (-10.0, 60.0), (9.0, 15.0), True),
]


class TestMetadados:
    def test_casas_decimais_medidas_em_producao(self) -> None:
        """§7.1: TT_04 e TT_06 terminaram em zero na 2ª casa em 29 de 29 leituras."""
        assert CAMPOS_POR_KEY["tt04"].casas_decimais == 1
        assert CAMPOS_POR_KEY["tt06"].casas_decimais == 1
        for key in ("tt01", "mt_01", "tt07", "mt07"):
            assert CAMPOS_POR_KEY[key].casas_decimais == 2

    def test_faixa_esperada_cabe_dentro_da_plausivel(self) -> None:
        for campo in CAMPOS:
            assert campo.plausivel[0] <= campo.esperada[0] < campo.esperada[1] <= campo.plausivel[1]

    def test_campos_obrigatorios_sao_os_que_alimentam_o_calculo(self) -> None:
        assert CAMPOS_OBRIGATORIOS == ["mt_01", "tt01", "tt04", "tt06", "mt07", "tt07"]


class TestFaixasDoAmbiente:
    def test_sem_variavel_mantem_as_faixas_medidas(self, monkeypatch) -> None:
        monkeypatch.delenv(ENV_FAIXAS_ESPERADAS, raising=False)
        assert aplicar_faixas_do_ambiente(BASE) == BASE

    def test_sobrescreve_so_o_campo_citado(self, monkeypatch) -> None:
        monkeypatch.setenv(ENV_FAIXAS_ESPERADAS, '{"tt01": [10, 28]}')
        resultado = {campo.key: campo for campo in aplicar_faixas_do_ambiente(BASE)}
        assert resultado["tt01"].esperada == (10.0, 28.0)
        assert resultado["tt04"].esperada == (9.0, 15.0)

    @pytest.mark.parametrize(
        "valor",
        ['{"tt01": [10]}', '{"tt01": [28, 10]}', '{"inexistente": [1, 2]}', "[]", "{nao json"],
    )
    def test_configuracao_invalida_falha_alto(self, monkeypatch, valor: str) -> None:
        """Silenciar aqui deixaria a planta classificando leituras pela faixa errada."""
        monkeypatch.setenv(ENV_FAIXAS_ESPERADAS, valor)
        with pytest.raises(ValueError):
            aplicar_faixas_do_ambiente(BASE)
