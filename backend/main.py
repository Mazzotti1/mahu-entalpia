from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from backend.database import init_db
from backend.routes.pontos import router as pontos_router

FRONTEND_DIR = Path(__file__).resolve().parent.parent
# Allowlist explícita: a raiz do projeto também guarda backend/simulador.db e docs/, que
# não devem ficar acessíveis ao servir a página na rede local.
ARQUIVOS_FRONTEND = {"index.html", "styles.css", "api.js", "app.js"}

ORIGENS_PADRAO = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    # "null" cobre a página aberta direto do disco (file://), como o README instrui.
    "null",
]


def origens_permitidas() -> list[str]:
    """Origens de CORS, com extras vindos de CARTA_CORS_ORIGINS (separadas por vírgula).

    Serve para liberar o IP da máquina na rede local ao testar pelo celular sem editar
    código. Acessando a página por /app/ não é necessário: ali a origem já é a mesma.
    """
    extras = os.getenv("CARTA_CORS_ORIGINS", "")
    return ORIGENS_PADRAO + [origem.strip() for origem in extras.split(",") if origem.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
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


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "API Simulador Psicrométrico ativa", "frontend": "/app/"}


@app.get("/app")
async def frontend_raiz() -> RedirectResponse:
    # Com a barra final os caminhos relativos da página resolvem para /app/styles.css.
    return RedirectResponse("/app/")


@app.get("/app/")
async def frontend_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/app/{arquivo}")
async def frontend_arquivo(arquivo: str) -> FileResponse:
    if arquivo not in ARQUIVOS_FRONTEND:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(FRONTEND_DIR / arquivo)
