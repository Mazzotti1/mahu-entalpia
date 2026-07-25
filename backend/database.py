from __future__ import annotations

import os
from contextlib import asynccontextmanager

import aiosqlite

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "simulador.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
            await db.executescript(schema_file.read())
        await db.commit()


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
