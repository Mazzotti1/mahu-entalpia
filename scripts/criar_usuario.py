"""Administração de contas pela linha de comando.

Não há tela de cadastro nem de "esqueci minha senha" de propósito: a planta tem um punhado
de operadores e um fluxo de recuperação por e-mail seria mais superfície de ataque do que
conveniência. Criar conta e trocar senha se faz aqui, por quem tem acesso ao servidor.

O banco nasce com a conta de instalação admin/admin, cuja senha é pública neste repositório.
Os dois primeiros comandos abaixo são o que deve ser feito com ela, na primeira subida:

    python -m scripts.criar_usuario renomear admin roberto
    python -m scripts.criar_usuario senha roberto

    python -m scripts.criar_usuario criar joana
    python -m scripts.criar_usuario listar
    python -m scripts.criar_usuario desativar joana

A senha nunca vem por argumento: `ps` mostra a linha de comando de qualquer processo, e o
histórico do shell a guardaria em disco. Ela é pedida por `getpass`, que não a ecoa.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

# Executado como `python -m scripts.criar_usuario` a partir da raiz do repositório, para
# que `backend` seja importável — é o mesmo padrão dos outros scripts desta pasta.
from backend.database import get_db, init_db
from backend.services.autenticacao import (
    criar_usuario,
    definir_senha,
    normalizar_username,
    renomear_usuario,
    revogar_todas,
)


def _pedir_senha() -> str:
    senha = getpass.getpass("Senha: ")
    if not senha:
        raise SystemExit("Senha vazia.")
    if senha != getpass.getpass("Repita a senha: "):
        raise SystemExit("As senhas não conferem.")
    # O bcrypt trunca em 72 bytes sem avisar; recusar aqui evita gravar um hash que não
    # corresponde ao que foi digitado.
    if len(senha.encode("utf-8")) > 72:
        raise SystemExit("A senha excede 72 bytes, o limite do bcrypt.")
    return senha


async def _criar(username: str, papel: str) -> None:
    senha = _pedir_senha()
    try:
        novo_id = await criar_usuario(username, senha, papel=papel)
    except ValueError as erro:
        raise SystemExit(str(erro)) from erro
    print(f"Usuário '{normalizar_username(username)}' criado (id {novo_id}, papel {papel}).")


async def _trocar_senha(username: str) -> None:
    senha = _pedir_senha()
    if not await definir_senha(username, senha):
        raise SystemExit(f"Usuário '{normalizar_username(username)}' não encontrado.")
    # `definir_senha` já derrubou as sessões: trocar a senha porque ela vazou não serve de
    # nada se quem a usou continuar dentro.
    print("Senha trocada. Todas as sessões abertas foram encerradas.")


async def _renomear(atual: str, novo: str) -> None:
    try:
        encontrado = await renomear_usuario(atual, novo)
    except ValueError as erro:
        raise SystemExit(str(erro)) from erro
    if not encontrado:
        raise SystemExit(f"Usuário '{normalizar_username(atual)}' não encontrado.")
    # Nada de derrubar sessões aqui: renomear não muda quem a pessoa é, e o id, que é o que
    # as sessões e a autoria referenciam, continua o mesmo.
    print(
        f"'{normalizar_username(atual)}' agora se chama '{normalizar_username(novo)}'. "
        "O histórico gravado sob este id continua sendo dele."
    )


async def _listar() -> None:
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT u.id, u.username, u.papel, u.ativo, u.ultimo_login_em,
                   (SELECT COUNT(*) FROM sessoes s
                     WHERE s.usuario_id = u.id
                       AND s.revogada_em IS NULL
                       AND s.expira_em > CURRENT_TIMESTAMP) AS sessoes_abertas
              FROM usuarios u
             ORDER BY u.id
            """
        )
        linhas = await cursor.fetchall()

    if not linhas:
        print("Nenhum usuário cadastrado.")
        return

    print(f"{'id':>3}  {'username':<20} {'papel':<10} {'ativo':<6} {'sessões':<8} último login")
    for linha in linhas:
        print(
            f"{linha['id']:>3}  {linha['username']:<20} {linha['papel']:<10} "
            f"{'sim' if linha['ativo'] else 'não':<6} {linha['sessoes_abertas']:<8} "
            f"{linha['ultimo_login_em'] or '-'}"
        )


async def _definir_ativo(username: str, ativo: bool) -> None:
    alvo = normalizar_username(username)
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE usuarios SET ativo = ? WHERE username = ?", (int(ativo), alvo)
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise SystemExit(f"Usuário '{alvo}' não encontrado.")
        busca = await db.execute("SELECT id FROM usuarios WHERE username = ?", (alvo,))
        linha = await busca.fetchone()

    if not ativo:
        # Desativar sem derrubar as sessões não desativa nada até o refresh vencer, o que
        # pode levar 30 dias.
        derrubadas = await revogar_todas(linha["id"], motivo="logout_global")
        print(f"Usuário '{alvo}' desativado. {derrubadas} sessão(ões) encerrada(s).")
    else:
        print(f"Usuário '{alvo}' reativado.")


async def principal(argumentos: argparse.Namespace) -> None:
    # Garante o schema antes de qualquer escrita: o script pode ser a primeira coisa a rodar
    # num banco novo, antes de a API subir.
    await init_db()

    if argumentos.comando == "criar":
        await _criar(argumentos.username, argumentos.papel)
    elif argumentos.comando == "senha":
        await _trocar_senha(argumentos.username)
    elif argumentos.comando == "renomear":
        await _renomear(argumentos.atual, argumentos.novo)
    elif argumentos.comando == "listar":
        await _listar()
    elif argumentos.comando == "desativar":
        await _definir_ativo(argumentos.username, False)
    elif argumentos.comando == "reativar":
        await _definir_ativo(argumentos.username, True)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="comando", required=True)

    criar = sub.add_parser("criar", help="Cria um usuário. A senha é pedida no prompt.")
    criar.add_argument("username")
    criar.add_argument("--papel", default="operador", choices=["operador", "admin"])

    senha = sub.add_parser("senha", help="Troca a senha e encerra as sessões abertas.")
    senha.add_argument("username")

    renomear = sub.add_parser(
        "renomear",
        help="Troca o nome de acesso, preservando id, senha e o histórico já gravado.",
    )
    renomear.add_argument("atual")
    renomear.add_argument("novo")

    sub.add_parser("listar", help="Lista os usuários e quantas sessões cada um tem abertas.")

    desativar = sub.add_parser("desativar", help="Bloqueia o acesso e derruba as sessões.")
    desativar.add_argument("username")

    reativar = sub.add_parser("reativar", help="Devolve o acesso a um usuário desativado.")
    reativar.add_argument("username")

    return parser


if __name__ == "__main__":
    try:
        asyncio.run(principal(montar_parser().parse_args()))
    except KeyboardInterrupt:
        sys.exit(130)
