"""Migrações aplicadas contra banco vazio e contra o banco de produção.

Exercita o SQL de `MIGRACOES`, não o invólucro assíncrono: o risco aqui é a migração 2
falhar num banco que já existe — `ALTER TABLE ... ADD COLUMN` não é idempotente, e o
`simulador.db` de produção está em `user_version = 0` com as tabelas da migração 1 já
criadas pelo `schema.sql` antigo.
"""

from __future__ import annotations

import os
import shutil
import sqlite3

import pytest

from backend.migrations import MIGRACOES

SNAPSHOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "simulador_snapshot.db"
)


def aplicar(conexao: sqlite3.Connection) -> int:
    """Mesma sequência de `aplicar_migracoes`, em sqlite3 síncrono."""
    versao = conexao.execute("PRAGMA user_version").fetchone()[0]
    for numero, script in MIGRACOES:
        if numero <= versao:
            continue
        conexao.executescript(script)
        conexao.execute(f"PRAGMA user_version = {numero}")
        conexao.commit()
        versao = numero
    return versao


def colunas(conexao: sqlite3.Connection, tabela: str) -> set[str]:
    return {linha[1] for linha in conexao.execute(f"PRAGMA table_info({tabela})")}


def tabelas(conexao: sqlite3.Connection) -> set[str]:
    return {
        linha[0] for linha in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


@pytest.fixture
def vazio(tmp_path):
    with sqlite3.connect(tmp_path / "novo.db") as conexao:
        yield conexao


class TestBancoNovo:
    def test_chega_na_ultima_versao(self, vazio) -> None:
        assert aplicar(vazio) == MIGRACOES[-1][0]

    def test_cria_todas_as_tabelas(self, vazio) -> None:
        aplicar(vazio)
        assert {
            "pontos_psicrometricos",
            "simulacoes",
            "simulacao_pontos",
            "leituras_ocr",
            "leituras_ocr_campos",
        } <= tabelas(vazio)

    def test_simulacoes_ganha_a_procedencia(self, vazio) -> None:
        aplicar(vazio)
        assert {"origem", "leitura_id"} <= colunas(vazio, "simulacoes")

    def test_reaplicar_e_inofensivo(self, vazio) -> None:
        """O boot roda as migrações toda vez; a segunda passada não pode fazer nada."""
        aplicar(vazio)
        assert aplicar(vazio) == MIGRACOES[-1][0]


@pytest.mark.skipif(not os.path.exists(SNAPSHOT), reason="snapshot de produção ausente")
class TestBancoDeProducao:
    @pytest.fixture
    def producao(self, tmp_path):
        copia = tmp_path / "producao.db"
        shutil.copy(SNAPSHOT, copia)
        with sqlite3.connect(copia) as conexao:
            yield conexao

    def test_parte_da_versao_zero(self, producao) -> None:
        assert producao.execute("PRAGMA user_version").fetchone()[0] == 0

    def test_migra_sem_perder_dados(self, producao) -> None:
        antes = producao.execute("SELECT COUNT(*) FROM simulacoes").fetchone()[0]
        pontos_antes = producao.execute("SELECT COUNT(*) FROM pontos_psicrometricos").fetchone()[0]

        aplicar(producao)

        assert producao.execute("SELECT COUNT(*) FROM simulacoes").fetchone()[0] == antes
        assert (
            producao.execute("SELECT COUNT(*) FROM pontos_psicrometricos").fetchone()[0]
            == pontos_antes
        )

    def test_linhas_existentes_ganham_origem_manual(self, producao) -> None:
        """As 29 leituras antigas não têm telemetria, então não podem alegar procedência."""
        aplicar(producao)
        origens = {
            linha[0] for linha in producao.execute("SELECT DISTINCT origem FROM simulacoes")
        }
        assert origens == {"manual"}

    def test_alter_table_nao_roda_duas_vezes(self, producao) -> None:
        aplicar(producao)
        aplicar(producao)
        assert "origem" in colunas(producao, "simulacoes")
