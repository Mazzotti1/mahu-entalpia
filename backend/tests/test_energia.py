"""Gasto térmico, contra o caso de referência da Parte I do documento."""

from __future__ import annotations

import pytest

from backend.services.energia import CP_AGUA, calcular_balanco, vazao_massica_ar_seco
from backend.services.processo import Setpoints, resolver_processo
from backend.services.psicrometria import estado_por_ur

ENTRADA = estado_por_ur(20.27, 64.09)


@pytest.fixture
def balanco():
    return calcular_balanco(resolver_processo(ENTRADA, Setpoints()))


def carga(balanco, de: str, para: str):
    return next(c for c in balanco.cargas if c.etapa.de == de and c.etapa.para == para)


class TestVazaoMassica:
    def test_usa_o_volume_especifico_da_entrada(self) -> None:
        """Decisão A: a vazão é medida em P1."""
        assert vazao_massica_ar_seco(36575.0, ENTRADA) == pytest.approx(12.039, abs=0.002)

    def test_medir_na_saida_daria_diferente(self) -> None:
        """Registra o tamanho da escolha A: ~0,4 % em todos os kW."""
        saida = resolver_processo(ENTRADA, Setpoints()).pontos["P5"]
        na_saida = vazao_massica_ar_seco(36575.0, saida)
        assert na_saida == pytest.approx(12.092, abs=0.002)
        assert 0.002 < na_saida / 12.039 - 1 < 0.006


class TestCasoDeReferencia:
    def test_vazao_massica(self, balanco) -> None:
        assert balanco.vazao_massica_kg_s == pytest.approx(12.039, abs=0.002)

    def test_resfriamento_com_desumidificacao(self, balanco) -> None:
        assert carga(balanco, "P1", "P2").q_kw == pytest.approx(-99.81, abs=0.05)

    def test_resfriamento_sobre_a_saturacao(self, balanco) -> None:
        assert carga(balanco, "P3", "P4").q_kw == pytest.approx(-100.34, abs=0.05)

    def test_reaquecimento(self, balanco) -> None:
        assert carga(balanco, "P4", "P5").q_kw == pytest.approx(130.73, abs=0.05)

    def test_totais(self, balanco) -> None:
        assert balanco.q_refrigeracao_kw == pytest.approx(200.15, abs=0.1)
        assert balanco.q_aquecimento_kw == pytest.approx(130.73, abs=0.05)

    def test_condensado(self, balanco) -> None:
        assert balanco.condensado_kg_h == pytest.approx(95.3, abs=0.2)

    def test_sem_umidificacao_neste_caso(self, balanco) -> None:
        assert balanco.agua_umidificacao_kg_h == 0.0


class TestDecomposicao:
    def test_sensivel_mais_latente_fecha_o_total(self, balanco) -> None:
        for c in balanco.cargas:
            assert c.q_sensivel_kw + c.q_latente_kw == pytest.approx(c.q_kw, abs=1e-9)

    def test_aquecimento_puro_nao_tem_latente(self, balanco) -> None:
        assert carga(balanco, "P4", "P5").q_latente_kw == pytest.approx(0.0, abs=1e-9)

    def test_etapa_nula_nao_gasta_nada(self, balanco) -> None:
        nula = carga(balanco, "P2", "P3")
        assert (nula.q_kw, nula.agua_kg_h, nula.condensado_kg_h) == (0.0, 0.0, 0.0)


class TestCorrecaoDoCondensado:
    def test_reduz_a_carga_da_serpentina(self, balanco) -> None:
        """O condensado sai pelo dreno levando entalpia que a água gelada não retirou."""
        c = carga(balanco, "P1", "P2")
        sem_correcao = balanco.vazao_massica_kg_s * c.etapa.delta_h
        assert abs(c.q_kw) < abs(sem_correcao)

    def test_tamanho_da_correcao(self, balanco) -> None:
        c = carga(balanco, "P1", "P2")
        esperada = (c.condensado_kg_h / 3600.0) * CP_AGUA * c.etapa.fim.tbs
        sem_correcao = balanco.vazao_massica_kg_s * c.etapa.delta_h
        assert c.q_kw - sem_correcao == pytest.approx(esperada, abs=1e-9)
        # Pequena, mas não desprezível a ponto de sumir: ~0,2 % desta etapa.
        assert 0.001 < esperada / abs(sem_correcao) < 0.01


class TestCasoSeco:
    """Com umidificação, o custo da etapa é água — não kW de serpentina."""

    @pytest.fixture
    def balanco_seco(self):
        processo = resolver_processo(estado_por_ur(24.0, 20.0), Setpoints(entalpia_alvo=30.0))
        return calcular_balanco(processo)

    def test_umidificacao_consome_agua(self, balanco_seco) -> None:
        assert balanco_seco.agua_umidificacao_kg_h > 0.0

    def test_a_entalpia_que_sobe_e_a_da_agua_de_reposicao(self, balanco_seco) -> None:
        """A umidificação adiabática não é isoentálpica, e a diferença tem nome.

        O bulbo úmido se conserva, mas a entalpia sobe um pouco: é a água de reposição
        entrando na corrente com entalpia própria, tomada na temperatura de bulbo úmido.
        Nada disso veio de serpentina.
        """
        umidificacao = next(
            c for c in balanco_seco.cargas if c.tipo == "umidificacao_adiabatica"
        )
        etapa = umidificacao.etapa
        assert etapa.fim.tbu == pytest.approx(etapa.inicio.tbu, abs=0.01)

        entalpia_da_agua = (
            balanco_seco.vazao_massica_kg_s * (etapa.delta_w / 1000.0) * CP_AGUA * etapa.inicio.tbu
        )
        assert umidificacao.q_kw == pytest.approx(entalpia_da_agua, rel=0.01)

    def test_umidificacao_fica_fora_dos_totais_de_kw(self, balanco_seco) -> None:
        """Somá-la contaria energia que nenhuma caldeira forneceu: o calor vem do ar."""
        soma_serpentinas = sum(
            abs(c.q_kw)
            for c in balanco_seco.cargas
            if c.tipo
            in ("aquecimento_sensivel", "resfriamento_sensivel", "resfriamento_desumidificacao")
        )
        assert balanco_seco.q_aquecimento_kw + balanco_seco.q_refrigeracao_kw == pytest.approx(
            soma_serpentinas, abs=1e-9
        )


class TestEscala:
    def test_kw_escala_linear_com_a_vazao(self) -> None:
        base = calcular_balanco(resolver_processo(ENTRADA, Setpoints()))
        dobro = calcular_balanco(resolver_processo(ENTRADA, Setpoints(vazao_m3h=73150.0)))
        assert dobro.q_refrigeracao_kw == pytest.approx(2 * base.q_refrigeracao_kw, rel=1e-9)
        assert dobro.condensado_kg_h == pytest.approx(2 * base.condensado_kg_h, rel=1e-9)
