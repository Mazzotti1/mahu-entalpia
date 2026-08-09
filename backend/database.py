from __future__ import annotations

import os
from contextlib import asynccontextmanager

import aiosqlite

from backend.migrations import aplicar_migracoes

BASE_DIR = os.path.dirname(__file__)

# Em container o banco vive num volume (CARTA_DB_PATH=/data/simulador.db); sem a variável
# fica ao lado do código, como na execução local.
DB_PATH = os.getenv("CARTA_DB_PATH") or os.path.join(BASE_DIR, "simulador.db")


async def init_db() -> int:
    """Leva o banco à versão de schema atual e devolve essa versão."""
    diretorio = os.path.dirname(DB_PATH)
    if diretorio:
        os.makedirs(diretorio, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        # WAL é gravado no arquivo do banco, então uma vez basta e vale para toda conexão
        # futura. Com ele um leitor deixa de bloquear o escritor — passa a importar agora
        # que renovar a sessão escreve em `sessoes` no meio de qualquer outra requisição.
        await db.execute("PRAGMA journal_mode = WAL")
        return await aplicar_migracoes(db)


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    # O SQLite ignora FOREIGN KEY por padrão, e é por conexão: as chaves declaradas desde a
    # migração 1 nunca foram aplicadas. Sem isto, `sessoes.usuario_id` apontando para um
    # usuário apagado seria aceito em silêncio — e uma sessão órfã é uma sessão válida.
    await db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
    finally:
        await db.close()
