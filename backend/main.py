from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db
from backend.routes.pontos import router as pontos_router
from backend.routes.processo import router as processo_router
from backend.services.telemetria_ocr import purgar_imagens_antigas

# O frontend é servido pelo nginx (container) ou pelo dev server do Vite, e nos dois casos
# /api chega por proxy na mesma origem — o CORS abaixo cobre só o acesso direto à API.
ORIGENS_PADRAO = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]


def origens_permitidas() -> list[str]:
    """Origens de CORS, com extras vindos de CARTA_CORS_ORIGINS (separadas por vírgula).

    Serve para liberar o IP da máquina na rede local ao testar pelo celular sem editar
    código. Pelo nginx não é necessário: ali a origem já é a mesma.
    """
    extras = os.getenv("CARTA_CORS_ORIGINS", "")
    return ORIGENS_PADRAO + [origem.strip() for origem in extras.split(",") if origem.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    # Depois das migrações: a purga consulta a tabela que a migração 2 cria.
    await purgar_imagens_antigas()
    yield


app = FastAPI(
    title="Simulador Psicrométrico API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origens_permitidas(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pontos_router)
app.include_router(processo_router)


@app.get("/")
async def root() -> dict[str, str]:
    """Também serve de healthcheck do container: responde sem tocar no banco."""
    return {"status": "API Simulador Psicrométrico ativa", "docs": "/docs"}
