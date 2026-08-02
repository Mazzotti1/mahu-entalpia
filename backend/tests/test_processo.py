"""O motor do processo, contra os números da Parte I do documento."""

from __future__ import annotations

import pytest

from backend.services.processo import (
    Setpoints,
    resfriar_ate_entalpia,
    resolver_processo,
    umidificar_adiabatico_ate_saturacao,
)
from backend.services.psicrometria import Estado, estado_por_ur, saturado_por_entalpia, saturado_por_w

# Caso de referência do documento: ar de retorno de 20,27 °C / 64,09 %.
ENTRADA = estado_por_ur(20.27, 64.09)
PADRAO = Setpoints()


def etapas_por_par(processo):
    return {(etapa.de, etapa.para): etapa for etapa in processo.etapas}


class TestPsicrometriaInversa:
    def test_saturado_por_w_e_o_orvalho_do_setpoint(self) -> None:
        estado = saturado_por_w(7.30)
        assert estado.tbs == pytest.approx(9.35, abs=0.01)
        assert estado.entalpia == pytest.approx(27.79, abs=0.01)
        assert estado.saturado

    def test_saturado_por_entalpia_cai_na_curva(self) -> None:
        estado = saturado_por_entalpia(36.20)
        assert estado.saturado
        assert estado.entalpia == pytest.approx(36.20, abs=0.01)
        assert estado.tbs == pytest.approx(12.83, abs=0.02)

    def test_entrada_de_referencia(self) -> None:
        assert ENTRADA.w == pytest.approx(9.50, abs=0.01)
        assert ENTRADA.entalpia == pytest.approx(44.51, abs=0.01)
        assert ENTRADA.volume_especifico == pytest.approx(0.8439, abs=0.0002)
        assert ENTRADA.ponto_orvalho == pytest.approx(13.27, abs=0.02)


class TestTransformacoes:
    def test_resfriar_sem_atingir_o_orvalho_e_sensivel(self) -> None:
        """Parando acima do orvalho (13,27 °C) o ar não condensa: reta horizontal."""
        alvo = ENTRADA.entalpia - 2.0
        fim, joelho = resfriar_ate_entalpia(ENTRADA, alvo)
        assert joelho is None
        assert fim.w == pytest.approx(ENTRADA.w, abs=1e-9)
        assert fim.tbs > ENTRADA.ponto_orvalho

    def test_resfriar_abaixo_do_orvalho_dobra_na_saturacao(self) -> None:
        fim, joelho = resfriar_ate_entalpia(ENTRADA, 36.20)
        assert joelho is not None
        # O joelho é o orvalho do ar de entrada: até ali W não muda.
        assert joelho.tbs == pytest.approx(ENTRADA.ponto_orvalho, abs=0.01)
        assert joelho.w == pytest.approx(ENTRADA.w, abs=1e-9)
        assert fim.saturado
        assert fim.entalpia == pytest.approx(36.20, abs=0.01)

    def test_aquecer_e_sempre_sensivel(self) -> None:
        fim, joelho = resfriar_ate_entalpia(ENTRADA, ENTRADA.entalpia + 5.0)
        assert joelho is None
        assert fim.w == pytest.approx(ENTRADA.w, abs=1e-9)
        assert fim.tbs > ENTRADA.tbs

    def test_umidificacao_preserva_o_bulbo_umido(self) -> None:
        seco = estado_por_ur(24.0, 20.0)
        fim = umidificar_adiabatico_ate_saturacao(seco)
        assert fim.saturado
        assert fim.tbu == pytest.approx(seco.tbu, abs=0.05)
        # Saturado, TBS e TBU coincidem — é o que o TT_06 do painel lê.
        assert fim.tbs == pytest.approx(fim.tbu, abs=0.05)
        assert fim.w > seco.w


class TestCasoFrio:
    """Ar de entrada úmido: W2 já passa do setpoint e a umidificação é pulada."""

    @pytest.fixture
    def processo(self):
        return resolver_processo(ENTRADA, PADRAO)

    def test_p2_sai_saturado_com_a_entalpia_alvo(self, processo) -> None:
        p2 = processo.pontos["P2"]
        assert p2.entalpia == pytest.approx(36.20, abs=0.01)
        assert p2.w == pytest.approx(9.23, abs=0.02)
        assert p2.saturado

    def test_umidificacao_e_pulada(self, processo) -> None:
        etapa = etapas_por_par(processo)[("P2", "P3")]
        assert etapa.tipo == "nula"
        assert not etapa.ativa
        assert processo.pontos["P3"] == processo.pontos["P2"]

    def test_p4_fica_no_setpoint_de_umidade(self, processo) -> None:
        p4 = processo.pontos["P4"]
        assert p4.w == pytest.approx(7.30, abs=0.001)
        assert p4.tbs == pytest.approx(9.35, abs=0.01)
        assert p4.saturado

    def test_p5_e_o_insuflamento_do_setpoint(self, processo) -> None:
        p5 = processo.pontos["P5"]
        assert p5.tbs == pytest.approx(20.0, abs=1e-9)
        assert p5.w == pytest.approx(7.30, abs=0.001)
        assert p5.ur == pytest.approx(50.26, abs=0.05)
        assert p5.entalpia == pytest.approx(38.65, abs=0.01)

    def test_tipos_das_etapas(self, processo) -> None:
        tipos = {par: etapa.tipo for par, etapa in etapas_por_par(processo).items()}
        assert tipos == {
            ("P1", "P2"): "resfriamento_desumidificacao",
            ("P2", "P3"): "nula",
            ("P3", "P4"): "resfriamento_desumidificacao",
            ("P4", "P5"): "aquecimento_sensivel",
        }

    def test_sem_avisos(self, processo) -> None:
        assert processo.avisos == []


class TestCasoSeco:
    """Ar de entrada seco: W2 fica abaixo do setpoint e o ramo de umidificação entra."""

    @pytest.fixture
    def processo(self):
        # 24 °C e 20 % dão ~3,7 g/kg, bem abaixo dos 7,30 do setpoint.
        return resolver_processo(estado_por_ur(24.0, 20.0), Setpoints(entalpia_alvo=30.0))

    def test_umidificacao_acontece(self, processo) -> None:
        etapa = etapas_por_par(processo)[("P2", "P3")]
        assert etapa.tipo == "umidificacao_adiabatica"
        assert etapa.delta_w > 0

    def test_umidifica_em_excesso_para_poder_descer(self, processo) -> None:
        """O over-shoot é o que torna o setpoint alcançável pela serpentina seguinte."""
        assert processo.pontos["P3"].w > processo.setpoints.w_saida
        assert processo.pontos["P4"].w == pytest.approx(7.30, abs=0.001)

    def test_termina_no_mesmo_insuflamento(self, processo) -> None:
        p5 = processo.pontos["P5"]
        assert p5.tbs == pytest.approx(20.0, abs=1e-9)
        assert p5.w == pytest.approx(7.30, abs=0.001)


class TestAvisos:
    def test_ar_seco_demais_para_o_setpoint(self) -> None:
        """Saturar não chega em 7,30: a etapa seguinte teria de aquecer, não resfriar."""
        processo = resolver_processo(
            estado_por_ur(10.0, 20.0), Setpoints(entalpia_alvo=12.0, w_saida=7.30)
        )
        assert "umidificacao_insuficiente" in {aviso.codigo for aviso in processo.avisos}

    def test_pressao_em_kpa_e_denunciada(self) -> None:
        """O erro de unidade do texto original: 101325 kPa são mil atmosferas."""
        processo = resolver_processo(ENTRADA, Setpoints(pressao_atm=101_325_000.0))
        assert "pressao_fora_da_faixa" in {aviso.codigo for aviso in processo.avisos}

    def test_alvo_acima_da_entrada_vira_aquecimento(self) -> None:
        processo = resolver_processo(ENTRADA, Setpoints(entalpia_alvo=60.0))
        assert "alvo_exige_aquecimento" in {aviso.codigo for aviso in processo.avisos}
        assert etapas_por_par(processo)[("P1", "P2")].tipo == "aquecimento_sensivel"


class TestPressaoDiferente:
    def test_altitude_desloca_o_orvalho_do_setpoint(self) -> None:
        """A 900 hPa o mesmo W corresponde a outra temperatura de saturação."""
        processo = resolver_processo(
            Estado(tbs=20.27, w=9.50, pressao_atm=90_000.0),
            Setpoints(pressao_atm=90_000.0),
        )
        assert processo.pontos["P4"].w == pytest.approx(7.30, abs=0.001)
        assert processo.pontos["P4"].tbs < 9.35
