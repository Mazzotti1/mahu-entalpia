from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db
from backend.routes.auth import router as auth_router
from backend.routes.pontos import router as pontos_router
from backend.routes.processo import router as processo_router
from backend.services.armazenamento_perfil import carregar_perfil_ativo
from backend.services.autenticacao import avisar_credenciais_padrao, purgar_sessoes
from backend.services.guardas import exigir_usuario
from backend.services.seguranca import em_producao
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
    # Semeia o perfil do código na primeira subida e fixa o vigente no processo. Ler o
    # perfil por requisição custaria uma ida ao banco em cada leitura para buscar uma
    # configuração que muda uma vez por semana, na melhor das hipóteses.
    await carregar_perfil_ativo()
    # Sessões mortas há mais de um mês não servem nem para auditoria nem para a detecção de
    # reúso de refresh, e a tabela cresce a cada renovação — uma por 5 minutos de uso.
    await purgar_sessoes()
    # Não bloqueia a subida: quem ainda não trocou a senha padrão precisa conseguir entrar
    # justamente para trocá-la. O que ele faz é impedir que o esquecimento passe calado.
    await avisar_credenciais_padrao()
    yield


app = FastAPI(
    title="Simulador Psicrométrico API",
    version="1.0.0",
    lifespan=lifespan,
    # O Swagger é um mapa completo da API, e nada nele é público depois do login. Em
    # produção sai do ar; em desenvolvimento continua onde sempre esteve.
    docs_url=None if em_producao() else "/docs",
    redoc_url=None if em_producao() else "/redoc",
    openapi_url=None if em_producao() else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origens_permitidas(),
    # Passou a ser True porque a autenticação é por cookie: sem isto, o acesso direto à API
    # (o `?api=` do frontend, usado para abrir a página pelo celular) chegaria sempre
    # anônimo. É seguro apenas porque `origens_permitidas()` é uma lista fechada — com
    # curinga, qualquer site do mundo passaria a falar pela sessão de quem o visitasse.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Público por definição: é o que se alcança sem estar autenticado.
app.include_router(auth_router)

# O guard fica no router, e não em cada rota: assim rota nova nasce fechada. Pendurar a
# dependência rota a rota faria da segurança uma questão de lembrança, e a que alguém
# esquecesse ficaria aberta sem avisar ninguém.
app.include_router(pontos_router, dependencies=[Depends(exigir_usuario)])
app.include_router(processo_router, dependencies=[Depends(exigir_usuario)])


@app.get("/")
async def root() -> dict[str, str]:
    """Também serve de healthcheck do container: responde sem tocar no banco."""
    return {"status": "API Simulador Psicrométrico ativa", "docs": "/docs"}
