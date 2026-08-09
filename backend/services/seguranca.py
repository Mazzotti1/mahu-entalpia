"""Primitivas de autenticação: hash de senha, JWT e cookies.

Só mecanismo. Quem decide se um login vale, abre sessão ou a derruba é
`services/autenticacao.py` — aqui não há nenhuma consulta ao banco.

O desenho é cookie, e não `Authorization: Bearer`, por duas razões que vêm do que já existe
no projeto:

1. O histórico usa `EventSource` (`useHistoricoStore`), e `EventSource` não deixa definir
   cabeçalho nenhum. Um token em header exigiria abandonar o SSE ou passar o token na query
   string, onde ele acabaria no log de acesso do nginx.
2. Frontend e API compartilham origem através do proxy do nginx, então o cookie viaja sem
   CORS e sem ficar legível por JavaScript — que é o que um token em `localStorage` não
   consegue oferecer contra XSS.

O preço do cookie é CSRF, pago com `SameSite=Strict` mais o double-submit de `_CSRF`.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Response

# Access curto porque ele é o que não dá para revogar entre uma renovação e outra: dentro
# dessa janela um token roubado vale. Refresh longo porque ele PODE ser revogado — está no
# banco — e é o que evita pedir senha toda semana a quem opera a planta todo dia.
ACCESS_TTL = timedelta(minutes=5)
REFRESH_TTL = timedelta(days=30)
# Corte por ociosidade, medido a partir de `sessoes.ultimo_uso_em`. Coisa diferente do teto
# de 30 dias: pega o navegador esquecido aberto num terminal que ninguém mais usa.
OCIOSIDADE_MAXIMA = timedelta(days=14)

ALGORITMO = "HS256"

COOKIE_ACCESS = "mahu_access"
COOKIE_REFRESH = "mahu_refresh"
COOKIE_CSRF = "mahu_csrf"

# O refresh só é enviado para as rotas que o renovam ou o encerram. Fora daí ele não tem o
# que fazer, e cada requisição que não o carrega é uma a menos por onde ele pode vazar.
CAMINHO_REFRESH = "/api/auth"

# Só para desenvolvimento, e por isso é um valor fixo e não um aleatório por processo: com
# aleatório, todo reload do uvicorn deslogaria quem está testando. Em produção o segredo é
# obrigatório e a API se recusa a subir sem ele (ver `_carregar_segredo`).
_SEGREDO_DEV = "dev-only-nao-use-em-producao"


def em_producao() -> bool:
    return os.getenv("CARTA_ENV", "").lower() in {"production", "producao", "prod"}


def _carregar_segredo() -> str:
    segredo = os.getenv("CARTA_JWT_SECRET", "").strip()
    if segredo:
        return segredo
    if em_producao():
        raise RuntimeError(
            "CARTA_JWT_SECRET não definido. Em produção a API não sobe sem ele: sem segredo "
            "próprio, qualquer um que conheça o padrão do projeto assina um token válido."
        )
    return _SEGREDO_DEV


SEGREDO = _carregar_segredo()


def cookies_seguros() -> bool:
    """`Secure` nos cookies. Ligado em produção; desligável para testar em http:// local.

    Em produção o proxy termina TLS, então o padrão segue o ambiente e ninguém precisa
    lembrar de configurar mais uma variável.
    """
    bruto = os.getenv("CARTA_COOKIE_SECURE")
    if bruto is not None:
        return bruto.strip().lower() in {"1", "true", "yes", "on"}
    return em_producao()


# --------------------------------------------------------------------------- senha


def hash_senha(senha: str) -> str:
    """bcrypt custo 12. Devolve o hash pronto para gravar, com salt embutido."""
    bytes_senha = senha.encode("utf-8")
    # O bcrypt usa só os primeiros 72 bytes e descarta o resto SEM AVISAR. Uma senha de 100
    # caracteres viraria uma de 72 e ninguém saberia. Não é política de senha: é recusar
    # gravar um hash que não corresponde ao que a pessoa digitou.
    if len(bytes_senha) > 72:
        raise ValueError("A senha excede 72 bytes, o limite do bcrypt.")
    return bcrypt.hashpw(bytes_senha, bcrypt.gensalt(rounds=12)).decode("ascii")


# Hash descartável, sobre uma senha aleatória que ninguém conhece, usado quando o username
# não existe. Sem ele, negar um usuário inexistente responderia em microssegundos e negar a
# senha errada levaria ~250 ms de bcrypt: o cronômetro diria quais contas existem, e a
# mensagem de erro única não teria protegido nada.
_HASH_BONECO = hash_senha(secrets.token_urlsafe(32))


def verificar_senha(senha: str, hash_armazenado: str | None) -> bool:
    """Confere a senha. Com `hash_armazenado=None`, gasta o mesmo tempo e devolve False."""
    alvo = hash_armazenado or _HASH_BONECO
    try:
        confere = bcrypt.checkpw(senha.encode("utf-8")[:72], alvo.encode("ascii"))
    except ValueError:
        # Hash corrompido no banco. Vale como senha errada, nunca como senha certa.
        return False
    return confere and hash_armazenado is not None


# --------------------------------------------------------------------------- tokens


def agora() -> datetime:
    return datetime.now(timezone.utc)


def novo_id_sessao() -> str:
    return str(uuid.uuid4())


def gerar_refresh() -> str:
    """32 bytes de aleatoriedade criptográfica. Só o cliente vê este valor."""
    return secrets.token_urlsafe(32)


def hash_refresh(token: str) -> str:
    """sha256, e não bcrypt: 256 bits aleatórios não têm dicionário que os ataque, e um
    bcrypt por renovação custaria centenas de milissegundos para não proteger nada a mais.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_confere(token: str, hash_armazenado: str) -> bool:
    """Comparação de tempo constante — `==` sobre hex vazaria o prefixo correto."""
    return hmac.compare_digest(hash_refresh(token), hash_armazenado)


def emitir_access(usuario_id: int, sessao_id: str) -> str:
    emitido = agora()
    return jwt.encode(
        {
            "sub": str(usuario_id),
            "sid": sessao_id,
            "iat": emitido,
            "exp": emitido + ACCESS_TTL,
        },
        SEGREDO,
        algorithm=ALGORITMO,
    )


def ler_access(token: str) -> tuple[int, str] | None:
    """(usuario_id, sessao_id) se o token for válido e não tiver expirado; senão None.

    `algorithms` é uma lista fechada de propósito: aceitar o algoritmo que o próprio token
    declara é como se assina um JWT com `alg: none`.
    """
    try:
        dados = jwt.decode(token, SEGREDO, algorithms=[ALGORITMO])
        return int(dados["sub"]), str(dados["sid"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def gerar_csrf() -> str:
    return secrets.token_urlsafe(32)


# --------------------------------------------------------------------------- cookies


def _definir(
    response: Response, nome: str, valor: str, *, max_age: int, caminho: str, http_only: bool
) -> None:
    response.set_cookie(
        key=nome,
        value=valor,
        max_age=max_age,
        path=caminho,
        httponly=http_only,
        secure=cookies_seguros(),
        # Strict e não Lax: nenhum fluxo aqui depende de chegar por link externo já logado,
        # e Strict é o que barra CSRF antes mesmo do double-submit precisar entrar.
        samesite="strict",
    )


def gravar_cookies_sessao(
    response: Response, *, access: str, refresh: str, csrf: str
) -> None:
    _definir(
        response,
        COOKIE_ACCESS,
        access,
        # Igual ao teto do refresh, não ao do access: o cookie precisa continuar sendo
        # enviado depois de o JWT vencer, senão o interceptador do frontend não teria como
        # saber que houve expiração e o pedido chegaria como anônimo.
        max_age=int(REFRESH_TTL.total_seconds()),
        caminho="/",
        http_only=True,
    )
    _definir(
        response,
        COOKIE_REFRESH,
        refresh,
        max_age=int(REFRESH_TTL.total_seconds()),
        caminho=CAMINHO_REFRESH,
        http_only=True,
    )
    # Legível por JavaScript de propósito: é a metade do double-submit que o frontend copia
    # para o cabeçalho `X-CSRF-Token`. Não é credencial — sozinho não autentica nada.
    _definir(
        response,
        COOKIE_CSRF,
        csrf,
        max_age=int(REFRESH_TTL.total_seconds()),
        caminho="/",
        http_only=False,
    )


def limpar_cookies_sessao(response: Response) -> None:
    """`path` tem de bater com o da gravação: o navegador trata cookies de caminhos
    diferentes como cookies diferentes, e apagar `/` deixaria o refresh vivo em `/api/auth`.
    """
    for nome, caminho in (
        (COOKIE_ACCESS, "/"),
        (COOKIE_REFRESH, CAMINHO_REFRESH),
        (COOKIE_CSRF, "/"),
    ):
        response.delete_cookie(
            key=nome,
            path=caminho,
            httponly=nome != COOKIE_CSRF,
            secure=cookies_seguros(),
            samesite="strict",
        )
