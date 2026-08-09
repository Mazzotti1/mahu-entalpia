"""Login, renovação e logout.

Único router público da API — é por definição o que se alcança sem estar autenticado. Todo
o resto entra por `Depends(exigir_usuario)` em `main.py`.

Nenhuma resposta daqui distingue "usuário não existe" de "senha errada" de "conta
desativada": os três saem como o mesmo 401 com o mesmo texto. Diferenciar transformaria o
formulário num verificador de quem trabalha na planta, que é metade do trabalho de quem vai
tentar adivinhar a senha depois.
"""
 
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.models import LoginInput, UsuarioResponse
from backend.services.autenticacao import (
    Usuario,
    abrir_sessao,
    autenticar,
    renovar,
    revogar_por_refresh,
    revogar_todas,
)
from backend.services.guardas import exigir_csrf, usuario_atual
from backend.services.seguranca import (
    COOKIE_REFRESH,
    emitir_access,
    gerar_csrf,
    gravar_cookies_sessao,
    limpar_cookies_sessao,
)

router = APIRouter(prefix="/api/auth", tags=["autenticacao"])

CREDENCIAIS_INVALIDAS = "Usuário ou senha inválidos."


def _ip_do_cliente(request: Request) -> str | None:
    """IP real por trás do proxy.

    O nginx preenche `X-Real-IP`; sem ele, `request.client` apontaria para o container do
    proxy e toda sessão pareceria vir do mesmo lugar. É registro para auditoria, não
    controle de acesso — nenhuma decisão de segurança pende deste valor, o que é bom, porque
    o cabeçalho é forjável por quem fale direto com a API.
    """
    encaminhado = request.headers.get("X-Real-IP") or request.headers.get("X-Forwarded-For")
    if encaminhado:
        return encaminhado.split(",")[0].strip()[:60]
    return request.client.host if request.client else None


def _abrir_cookies(response: Response, usuario_id: int, sessao_id: str, refresh: str) -> None:
    gravar_cookies_sessao(
        response,
        access=emitir_access(usuario_id, sessao_id),
        refresh=refresh,
        csrf=gerar_csrf(),
    )


@router.post("/login", response_model=UsuarioResponse)
async def login(
    credenciais: LoginInput, request: Request, response: Response
) -> UsuarioResponse:
    """Abre sessão e devolve os três cookies.

    Sem CSRF aqui: não existe sessão anterior para proteger, e não há cookie de onde o
    cliente pudesse copiar o token. `SameSite=Strict` cobre o login forjado.
    """
    usuario = await autenticar(credenciais.username, credenciais.senha)
    if usuario is None:
        raise HTTPException(status_code=401, detail=CREDENCIAIS_INVALIDAS)

    sessao_id, refresh = await abrir_sessao(
        usuario.id,
        user_agent=request.headers.get("User-Agent"),
        ip=_ip_do_cliente(request),
    )
    _abrir_cookies(response, usuario.id, sessao_id, refresh)
    return UsuarioResponse(id=usuario.id, username=usuario.username, papel=usuario.papel)


@router.post("/refresh", response_model=UsuarioResponse)
async def refresh_sessao(
    request: Request, response: Response, _: None = Depends(exigir_csrf)
) -> UsuarioResponse:
    """Troca o refresh por um par novo. O anterior é queimado na hora.

    Falhar aqui limpa os cookies: um refresh recusado não vai passar a valer sozinho, e
    deixá-lo no navegador só faria o cliente repetir a tentativa a cada requisição.
    """
    token = request.cookies.get(COOKIE_REFRESH)
    if not token:
        limpar_cookies_sessao(response)
        raise HTTPException(status_code=401, detail="Sessão ausente ou expirada.")

    resultado = await renovar(token)
    if resultado is None:
        limpar_cookies_sessao(response)
        raise HTTPException(status_code=401, detail="Sessão ausente ou expirada.")

    sessao, novo_refresh = resultado
    _abrir_cookies(response, sessao.usuario.id, sessao.id, novo_refresh)
    return UsuarioResponse(
        id=sessao.usuario.id, username=sessao.usuario.username, papel=sessao.usuario.papel
    )


@router.post("/logout", status_code=204, response_class=Response)
async def logout(
    request: Request, response: Response, _: None = Depends(exigir_csrf)
) -> Response:
    """Encerra a sessão no servidor e apaga os cookies.

    Sem `Depends(usuario_atual)`: sair tem de funcionar com o access token já vencido, que é
    justamente quando alguém costuma clicar em sair. A sessão é localizada pelo refresh.

    204 mesmo quando não havia sessão nenhuma. Sair de lugar nenhum é sair.
    """
    token = request.cookies.get(COOKIE_REFRESH)
    if token:
        await revogar_por_refresh(token, motivo="logout")

    limpar_cookies_sessao(response)
    return Response(status_code=204)


@router.post("/logout-global", status_code=204, response_class=Response)
async def logout_global(
    response: Response,
    usuario: Usuario = Depends(usuario_atual),
    _: None = Depends(exigir_csrf),
) -> Response:
    """Derruba todas as sessões do usuário, inclusive esta.

    É o botão para quando se suspeita de cookie copiado: só apagar o do próprio navegador
    não alcança a cópia que está em outro.
    """
    await revogar_todas(usuario.id, motivo="logout_global")
    limpar_cookies_sessao(response)
    return Response(status_code=204)


@router.get("/me", response_model=UsuarioResponse)
async def eu(usuario: Usuario = Depends(usuario_atual)) -> UsuarioResponse:
    """Quem está autenticado. É por aqui que o frontend descobre, ao abrir a página, se já
    existe sessão — sem isto o navegador teria de mostrar o login antes de saber.
    """
    return UsuarioResponse(id=usuario.id, username=usuario.username, papel=usuario.papel)
