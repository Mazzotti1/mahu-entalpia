"""As dependências que fecham a API.

Ficam num router inteiro, não em cada rota:

    app.include_router(pontos_router, dependencies=[Depends(exigir_usuario)])

Assim rota nova nasce protegida. Pendurar `Depends` rota a rota transforma segurança em
disciplina, e a rota que alguém esquecer de anotar não avisa que ficou aberta.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from backend.services.autenticacao import Usuario, sessao_viva
from backend.services.seguranca import COOKIE_ACCESS, COOKIE_CSRF, ler_access

CABECALHO_CSRF = "X-CSRF-Token"

# GET, HEAD e OPTIONS não mudam estado, e o SSE (um GET) não teria como mandar cabeçalho
# nenhum — o `EventSource` não permite. Exigir CSRF deles quebraria o histórico sem defender
# coisa alguma.
METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})

# Uma mensagem só para token ausente, token inválido e sessão revogada. Distingui-las diria
# a um curioso em qual das três situações ele está, e nenhuma dessas informações ajuda quem
# tem direito de entrar.
_NAO_AUTENTICADO = "Sessão ausente ou expirada."


async def usuario_atual(request: Request) -> Usuario:
    """Valida o access token e confirma que a sessão dele continua de pé.

    O JWT sozinho não basta: ele é autoassinado e não sabe que houve logout. A consulta a
    `sessoes` é o que faz sair da conta valer imediatamente, e custa um SELECT por chave
    primária.
    """
    # A mesma requisição costuma pedir o usuário duas vezes — uma pela dependência do router
    # e outra pelo parâmetro do endpoint que grava a autoria. Sem este cache seriam dois
    # SELECT idênticos por requisição.
    em_cache = getattr(request.state, "usuario", None)
    if em_cache is not None:
        return em_cache

    from backend.services.seguranca import COOKIE_ACCESS

    token = request.cookies.get(COOKIE_ACCESS)
    if not token:
        raise HTTPException(status_code=401, detail=_NAO_AUTENTICADO)

    identificacao = ler_access(token)
    if identificacao is None:
        raise HTTPException(status_code=401, detail=_NAO_AUTENTICADO)

    _, sessao_id = identificacao
    sessao = await sessao_viva(sessao_id)
    if sessao is None:
        raise HTTPException(status_code=401, detail=_NAO_AUTENTICADO)

    request.state.usuario = sessao.usuario
    request.state.sessao_id = sessao.id
    return sessao.usuario


def exigir_csrf(request: Request) -> None:
    """Double-submit: o cabeçalho tem de repetir o cookie `mahu_csrf`.

    `SameSite=Strict` já barra a requisição forjada de outro site antes de chegar aqui. Este
    é o segundo cadeado, para o caso de um navegador antigo ignorar o atributo — outro site
    consegue mandar a requisição, mas não consegue LER o cookie para copiá-lo no cabeçalho.
    """
    if request.method in METODOS_SEGUROS:
        return

    do_cookie = request.cookies.get(COOKIE_CSRF)
    do_cabecalho = request.headers.get(CABECALHO_CSRF)
    if not do_cookie or not do_cabecalho or do_cookie != do_cabecalho:
        # 403 e não 401 de propósito: o frontend renova a sessão ao ver 401, e um 401 aqui
        # o mandaria renovar em laço por um problema que renovar não resolve.
        raise HTTPException(status_code=403, detail="Requisição sem token CSRF válido.")


async def exigir_usuario(
    _: None = Depends(exigir_csrf), usuario: Usuario = Depends(usuario_atual)
) -> Usuario:
    """Sessão válida mais CSRF nos métodos que mudam estado. É o guard dos routers."""
    return usuario
