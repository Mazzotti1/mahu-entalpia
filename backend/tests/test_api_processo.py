"""A API do processo de ponta a ponta, contra um banco temporário.

Não cobre `/api/mahu/ler`: aquele caminho precisa de OpenCV e do easyocr, que só existem no
ambiente completo. O que ele produz — os campos conferidos — entra aqui por
`/api/mahu/processo`, que é o resto do fluxo.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi", reason="ambiente sem FastAPI")
pytest.importorskip("aiosqlite", reason="ambiente sem aiosqlite")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

CAMPOS_MAHU = {
    "tt01": 20.27,
    "mt_01": 64.09,
    "tt04": 12.20,
    "tt06": 8.70,
    "tt07": 21.20,
    "mt07": 46.48,
}


@pytest.fixture(scope="module")
def cliente():
    # O `with` dispara o lifespan, que aplica as migrações no banco temporário.
    with TestClient(app) as client:
        yield client


class TestSetpoints:
    def test_comeca_com_os_valores_semeados(self, cliente) -> None:
        corpo = cliente.get("/api/setpoints").json()
        assert corpo["w_saida"] == 7.30
        assert corpo["tbs_final"] == 20.0
        assert corpo["pressao_atm"] == 101325.0

    def test_atualiza_e_persiste(self, cliente) -> None:
        novo = {
            "w_saida": 8.0,
            "tbs_final": 22.0,
            "entalpia_alvo": 38.0,
            "vazao_m3h": 40000.0,
            "pressao_atm": 101325.0,
        }
        assert cliente.put("/api/setpoints", json=novo).status_code == 200
        assert cliente.get("/api/setpoints").json()["w_saida"] == 8.0
        # Devolve ao padrão para não contaminar os testes seguintes.
        cliente.put(
            "/api/setpoints",
            json={
                "w_saida": 7.30,
                "tbs_final": 20.0,
                "entalpia_alvo": 36.20,
                "vazao_m3h": 36575.0,
                "pressao_atm": 101325.0,
            },
        )

    def test_pressao_em_kpa_e_recusada(self, cliente) -> None:
        """O erro de unidade do texto original não pode entrar pela API."""
        resposta = cliente.put(
            "/api/setpoints",
            json={
                "w_saida": 7.30,
                "tbs_final": 20.0,
                "entalpia_alvo": 36.20,
                "vazao_m3h": 36575.0,
                "pressao_atm": 101_325_000.0,
            },
        )
        assert resposta.status_code == 422


class TestProcesso:
    @pytest.fixture(scope="class")
    def corpo(self, cliente):
        resposta = cliente.post("/api/processo", json={"tbs": 20.27, "ur": 64.09})
        assert resposta.status_code == 200, resposta.text
        return resposta.json()

    def test_devolve_os_cinco_pontos(self, corpo) -> None:
        assert [p["label"] for p in corpo["pontos"]] == ["P1", "P2", "P3", "P4", "P5"]

    def test_pontos_de_referencia(self, corpo) -> None:
        pontos = {p["label"]: p for p in corpo["pontos"]}
        assert pontos["P2"]["entalpia"] == pytest.approx(36.20, abs=0.02)
        assert pontos["P4"]["w"] == pytest.approx(7.30, abs=0.01)
        assert pontos["P4"]["tbs"] == pytest.approx(9.35, abs=0.02)
        assert pontos["P5"]["tbs"] == pytest.approx(20.0, abs=0.01)
        assert pontos["P5"]["ur"] == pytest.approx(50.26, abs=0.1)

    def test_etapas_com_tipo_e_carga(self, corpo) -> None:
        etapas = {(e["de"], e["para"]): e for e in corpo["etapas"]}
        assert etapas[("P1", "P2")]["tipo"] == "resfriamento_desumidificacao"
        assert etapas[("P2", "P3")]["ativa"] is False
        assert etapas[("P4", "P5")]["tipo"] == "aquecimento_sensivel"
        assert etapas[("P4", "P5")]["q_kw"] == pytest.approx(130.73, abs=0.1)

    def test_joelho_marca_onde_a_trajetoria_dobra(self, corpo) -> None:
        """É o que permite desenhar o trecho reto e o trecho sobre a saturação."""
        etapa = next(e for e in corpo["etapas"] if (e["de"], e["para"]) == ("P1", "P2"))
        assert etapa["joelho"] is not None
        assert etapa["joelho"]["tbs"] == pytest.approx(13.27, abs=0.05)

    def test_totais(self, corpo) -> None:
        totais = corpo["totais"]
        assert totais["vazao_massica_kg_s"] == pytest.approx(12.039, abs=0.005)
        assert totais["q_refrigeracao_kw"] == pytest.approx(200.15, abs=0.2)
        assert totais["q_aquecimento_kw"] == pytest.approx(130.73, abs=0.1)
        assert totais["condensado_kg_h"] == pytest.approx(95.3, abs=0.3)

    def test_persiste_e_aparece_no_historico(self, cliente, corpo) -> None:
        assert corpo["simulacao_id"] is not None
        simulacao = cliente.get(f"/api/simulacao/{corpo['simulacao_id']}").json()
        assert len(simulacao["pontos"]) == 5

    def test_processo_pode_ser_relido_pelo_historico(self, cliente, corpo) -> None:
        """Sem isto, abrir uma leitura antiga mostraria pontos sem etapa nem kW."""
        relido = cliente.get(f"/api/simulacao/{corpo['simulacao_id']}/processo").json()
        assert [p["label"] for p in relido["pontos"]] == ["P1", "P2", "P3", "P4", "P5"]
        assert relido["totais"]["q_refrigeracao_kw"] == pytest.approx(
            corpo["totais"]["q_refrigeracao_kw"], abs=0.01
        )
        assert [e["tipo"] for e in relido["etapas"]] == [e["tipo"] for e in corpo["etapas"]]
        # O joelho sobrevive à ida e volta pelo banco: é dele que depende a trajetória.
        etapa = next(e for e in relido["etapas"] if (e["de"], e["para"]) == ("P1", "P2"))
        assert etapa["joelho"]["tbs"] == pytest.approx(13.27, abs=0.05)

    def test_simulacao_sem_processo_da_404(self, cliente) -> None:
        antiga = cliente.post(
            "/api/simulacao",
            json={"nome": "avulsa", "pontos": [{"label": "P1", "tbs": 20.0, "ur": 50.0}]},
        ).json()
        assert cliente.get(f"/api/simulacao/{antiga['id']}/processo").status_code == 404

    def test_setpoints_do_corpo_sobrepoem_os_gravados(self, cliente) -> None:
        resposta = cliente.post(
            "/api/processo",
            json={
                "tbs": 20.27,
                "ur": 64.09,
                "setpoints": {
                    "w_saida": 6.0,
                    "tbs_final": 18.0,
                    "entalpia_alvo": 36.20,
                    "vazao_m3h": 36575.0,
                    "pressao_atm": 101325.0,
                },
            },
        )
        pontos = {p["label"]: p for p in resposta.json()["pontos"]}
        assert pontos["P4"]["w"] == pytest.approx(6.0, abs=0.01)
        assert pontos["P5"]["tbs"] == pytest.approx(18.0, abs=0.01)


class TestProcessoDoMahu:
    @pytest.fixture(scope="class")
    def corpo(self, cliente):
        resposta = cliente.post("/api/mahu/processo", json=CAMPOS_MAHU)
        assert resposta.status_code == 200, resposta.text
        return resposta.json()

    def test_so_tt01_e_mt01_alimentam_o_calculo(self, corpo) -> None:
        """P1 é o ar de entrada lido; o resto do processo vem dos setpoints."""
        p1 = next(p for p in corpo["pontos"] if p["label"] == "P1")
        assert p1["tbs"] == pytest.approx(20.27, abs=0.01)
        assert p1["w"] == pytest.approx(9.50, abs=0.02)

    def test_medicoes_viram_desvio(self, corpo) -> None:
        desvios = {d["campo"]: d for d in corpo["desvios"]}
        assert set(desvios) >= {"tt04", "tt06", "tt07", "mt07"}
        # TT07 = 21,20 °C medido contra os 20 °C do setpoint: +1,2 °C de desvio.
        assert desvios["tt07"]["medido"] == pytest.approx(21.20, abs=0.01)
        assert desvios["tt07"]["calculado"] == pytest.approx(20.0, abs=0.01)
        assert desvios["tt07"]["diferenca"] == pytest.approx(1.20, abs=0.02)

    def test_totais_iguais_ao_caso_de_referencia(self, corpo) -> None:
        assert corpo["totais"]["q_refrigeracao_kw"] == pytest.approx(200.15, abs=0.2)
