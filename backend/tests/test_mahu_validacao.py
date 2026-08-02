"""Validação cruzada — inclusive contra a leitura #28, que hoje está no banco de produção."""

from __future__ import annotations

import pytest

from backend.services.mahu_validacao import LeituraAnterior, validar_leitura

# Leitura #12 do snapshot: sadia, atravessa todos os validadores.
BOA = {
    "tt01": 16.64,
    "mt_01": 84.53,
    "tt04": 11.80,
    "tt06": 8.80,
    "tt07": 20.49,
    "mt07": 48.75,
}

# Leitura #28: os quatro campos do bloco esquerdo corrompidos de uma vez, com TT07/MT07
# corretos. Nenhuma checagem por campo pegou — foi assim que ela entrou no banco.
LEITURA_28 = {
    "tt01": 13.50,
    "mt_01": 54.94,
    "tt04": 16.80,
    "tt06": 9.60,
    "tt07": 19.92,
    "mt07": 50.32,
}


def codigos(valores, anterior=None) -> set[str]:
    return {aviso.codigo for aviso in validar_leitura(valores, anterior)}


class TestLeiturasReais:
    def test_leitura_boa_nao_gera_aviso(self) -> None:
        assert validar_leitura(BOA) == []

    @pytest.mark.parametrize("sid", [1, 2, 3, 12, 20, 29])
    def test_amostra_do_snapshot_passa_limpa(self, sid: int) -> None:
        """Falso positivo aqui custaria conferência manual em leitura boa."""
        amostras = {
            1: (20.27, 63.89, 12.20, 8.70, 21.20, 46.48),
            2: (21.21, 70.38, 13.10, 8.70, 21.15, 46.52),
            3: (15.38, 87.37, 11.30, 8.90, 19.76, 50.99),
            12: (16.64, 84.53, 11.80, 8.80, 20.49, 48.75),
            20: (18.23, 74.99, 12.60, 8.70, 20.58, 48.52),
            29: (17.62, 88.53, 12.40, 8.70, 19.27, 52.24),
        }
        tt01, mt_01, tt04, tt06, tt07, mt07 = amostras[sid]
        assert validar_leitura(
            {"tt01": tt01, "mt_01": mt_01, "tt04": tt04, "tt06": tt06, "tt07": tt07, "mt07": mt07}
        ) == []

    def test_leitura_28_e_pega(self) -> None:
        encontrados = codigos(LEITURA_28)
        # TT_04 = 16,80 é maior que TT01 = 13,50: o ar teria esquentado na serpentina fria.
        assert "cadeia_de_resfriamento" in encontrados
        # E o ar de entrada sairia seco demais para condensar em TT_04.
        assert "p2_nao_satura" in encontrados


class TestUmidadeDeSaida:
    def test_desvio_pequeno_passa(self) -> None:
        """O pior caso das 29 leituras (#8, +1,2%) não pode virar aviso."""
        assert "w_saida_fora_do_setpoint" not in codigos({"tt07": 19.52, "mt07": 52.42})

    def test_virgula_perdida_no_mt07_e_pega(self) -> None:
        assert "w_saida_fora_do_setpoint" in codigos({"tt07": 20.49, "mt07": 4.87})

    def test_campos_ausentes_nao_geram_aviso(self) -> None:
        assert validar_leitura({"tt07": 20.49}) == []


class TestInformativos:
    def test_umd_abs_coerente_passa(self) -> None:
        assert "umd_abs_divergente" not in codigos({**BOA, "umd_abs_pv": 7.30})

    def test_umd_abs_divergente_e_pego(self) -> None:
        assert "umd_abs_divergente" in codigos({**BOA, "umd_abs_pv": 9.80})

    def test_entalpia_coerente_passa(self) -> None:
        # TT_04 = 11,80 °C saturado dá ~33,6 kJ/kg.
        assert "entalpia_divergente" not in codigos({**BOA, "tt04_entalpia_pv": 33.60})

    def test_entalpia_divergente_e_pega(self) -> None:
        assert "entalpia_divergente" in codigos({**BOA, "tt04_entalpia_pv": 68.00})


class TestContinuidade:
    def test_leitura_proxima_e_parecida_passa(self) -> None:
        anterior = LeituraAnterior(valores=BOA, minutos=8.0)
        assert codigos({**BOA, "tt01": 16.79}, anterior) == set()

    def test_salto_dentro_da_janela_e_pego(self) -> None:
        anterior = LeituraAnterior(valores=BOA, minutos=8.0)
        assert "salto_temporal" in codigos({**BOA, "tt01": 19.90}, anterior)

    def test_fora_da_janela_nao_compara(self) -> None:
        """Duas horas depois a planta mudou mesmo; comparar seria ruído."""
        anterior = LeituraAnterior(valores=BOA, minutos=120.0)
        assert codigos({**BOA, "tt01": 19.90}, anterior) == set()
