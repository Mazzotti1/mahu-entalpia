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
        return await aplicar_migracoes(db)


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
