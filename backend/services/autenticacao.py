"""Regras de sessão: abrir, validar, renovar e derrubar.

Toda a conversa com o banco de autenticação passa por aqui. `services/seguranca.py` cuida
das primitivas (bcrypt, JWT, cookies) e não sabe que existe banco; as rotas não montam SQL.

Duas escolhas que valem o comentário:

**A sessão vive no banco, não só no JWT.** Um JWT autoassinado não sabe ser cancelado — sair
da conta apagaria o cookie e uma cópia do token seguiria valendo até vencer. Com a linha em
`sessoes`, `revogar` derruba o acesso na requisição seguinte, inclusive um SSE já aberto.
O custo é um SELECT por chave primária a cada requisição, que ao lado de psicrometria e OCR
não aparece no relógio.

**O refresh rotaciona e a rotação é vigiada.** Cada renovação queima o refresh anterior. Se o
queimado reaparecer, existem duas cópias do cookie em circulação e uma delas não é do dono:
a cadeia inteira cai, e o legítimo é obrigado a entrar de novo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from backend.database import get_db
from backend.services.seguranca import (
    OCIOSIDADE_MAXIMA,
    REFRESH_TTL,
    agora,
    gerar_refresh,
    hash_refresh,
    hash_senha,
    novo_id_sessao,
    verificar_senha,
)

_log = logging.getLogger(__name__)

# O formato do CURRENT_TIMESTAMP do SQLite, sempre em UTC. Gravar as datas calculadas em
# Python no mesmo formato é o que permite compará-las com as do banco em SQL.
_FORMATO_SQLITE = "%Y-%m-%d %H:%M:%S"

# A conta que a migração 8 semeia para o primeiro login ser possível. Ver
# `avisar_credenciais_padrao`.
USUARIO_PADRAO = "admin"
SENHA_PADRAO = "admin"


def _texto(momento: datetime) -> str:
    return momento.strftime(_FORMATO_SQLITE)


@dataclass(frozen=True)
class Usuario:
    id: int
    username: str
    papel: str


@dataclass(frozen=True)
class Sessao:
    id: str
    usuario: Usuario


def normalizar_username(username: str) -> str:
    """Minúsculas e sem espaço nas pontas.

    A coluna é `COLLATE NOCASE`, então o banco já recusaria a duplicata; normalizar aqui
    é para que o que se grava seja igual ao que se compara, e para que a telemetria não
    tenha "Roberto" e "roberto" como duas coisas.
    """
    return username.strip().lower()


# --------------------------------------------------------------------------- login


async def autenticar(username: str, senha: str) -> Usuario | None:
    """Usuário e senha conferem e a conta está ativa? Senão None — sem dizer qual dos três.

    Usuário inexistente também gasta um bcrypt (`verificar_senha` com `None`). Sem isso a
    negativa sairia em microssegundos para conta inexistente e em ~250 ms para senha errada,
    e o cronômetro entregaria a lista de usuários que a mensagem única esconde.
    """
    alvo = normalizar_username(username)
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, username, papel, senha_hash, ativo FROM usuarios WHERE username = ?",
            (alvo,),
        )
        linha = await cursor.fetchone()

    hash_armazenado = linha["senha_hash"] if linha else None
    if not verificar_senha(senha, hash_armazenado):
        return None
    # Conta desativada só é checada DEPOIS do bcrypt: sair antes devolveria a resposta rápida
    # e revelaria que a conta existe.
    if not linha["ativo"]:
        return None

    async with get_db() as db:
        await db.execute(
            "UPDATE usuarios SET ultimo_login_em = CURRENT_TIMESTAMP WHERE id = ?",
            (linha["id"],),
        )
        await db.commit()

    return Usuario(id=linha["id"], username=linha["username"], papel=linha["papel"])


# --------------------------------------------------------------------------- sessão


async def abrir_sessao(
    usuario_id: int, *, user_agent: str | None, ip: str | None
) -> tuple[str, str]:
    """Cria a sessão e devolve `(sessao_id, refresh em claro)`.

    O refresh em claro sai daqui uma única vez, para virar cookie. O banco fica só com o
    sha256: vazar a tabela não pode entregar sessão ativa nenhuma.
    """
    sessao_id = novo_id_sessao()
    refresh = gerar_refresh()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO sessoes (
                id, usuario_id, refresh_hash, expira_em, ultimo_uso_em, user_agent, ip
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
            """,
            (
                sessao_id,
                usuario_id,
                hash_refresh(refresh),
                _texto(agora() + REFRESH_TTL),
                (user_agent or "")[:300] or None,
                ip,
            ),
        )
        await db.commit()
    return sessao_id, refresh


_SELECT_SESSAO_VIVA = """
    SELECT s.id, s.usuario_id, s.refresh_hash, u.username, u.papel
      FROM sessoes s
      JOIN usuarios u ON u.id = s.usuario_id
     WHERE s.id = ?
       AND s.revogada_em IS NULL
       AND s.expira_em > CURRENT_TIMESTAMP
       AND s.ultimo_uso_em > ?
       AND u.ativo = 1
"""


async def sessao_viva(sessao_id: str) -> Sessao | None:
    """A sessão ainda vale? Chamada em toda requisição autenticada e no batimento do SSE.

    Três formas de morrer, e as três importam: revogada (logout, senha trocada, reúso),
    vencida pelo teto absoluto, ou parada além do limite de ociosidade. Usuário desativado
    conta como quarta — desativar precisa valer para as sessões que já estavam abertas.
    """
    limite_ocioso = _texto(agora() - OCIOSIDADE_MAXIMA)
    async with get_db() as db:
        cursor = await db.execute(_SELECT_SESSAO_VIVA, (sessao_id, limite_ocioso))
        linha = await cursor.fetchone()
    if not linha:
        return None
    return Sessao(
        id=linha["id"],
        usuario=Usuario(
            id=linha["usuario_id"], username=linha["username"], papel=linha["papel"]
        ),
    )


async def renovar(refresh: str) -> tuple[Sessao, str] | None:
    """Rotaciona o refresh e devolve `(sessão nova, refresh novo)`. None se não valer.

    A sessão antiga é encerrada e apontada para a nova. Reapresentar um refresh já
    rotacionado é sinal de cookie copiado: a cadeia inteira cai, porque não há como saber
    qual das duas pontas é o dono e manter a errada viva é pior do que exigir novo login.
    """
    alvo = hash_refresh(refresh)
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT s.id, s.usuario_id, s.revogada_em, s.motivo_revogacao, s.substituida_por,
                   s.user_agent, s.ip, s.expira_em, s.ultimo_uso_em, u.username, u.papel,
                   u.ativo
              FROM sessoes s
              JOIN usuarios u ON u.id = s.usuario_id
             WHERE s.refresh_hash = ?
            """,
            (alvo,),
        )
        linha = await cursor.fetchone()

    if not linha:
        return None

    if linha["revogada_em"] is not None:
        if linha["motivo_revogacao"] == "rotacao":
            await _derrubar_cadeia(linha["id"])
        return None

    if not linha["ativo"]:
        return None

    momento = agora()
    if linha["expira_em"] <= _texto(momento):
        await revogar(linha["id"], motivo="expirada")
        return None
    if linha["ultimo_uso_em"] is not None and linha["ultimo_uso_em"] <= _texto(
        momento - OCIOSIDADE_MAXIMA
    ):
        await revogar(linha["id"], motivo="ociosa")
        return None

    nova_id = novo_id_sessao()
    novo_refresh = gerar_refresh()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO sessoes (
                id, usuario_id, refresh_hash, expira_em, ultimo_uso_em, user_agent, ip
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
            """,
            (
                nova_id,
                linha["usuario_id"],
                hash_refresh(novo_refresh),
                # O teto absoluto é herdado, e não recontado: renovar não pode esticar o
                # prazo, senão uma sessão em uso diário nunca terminaria.
                linha["expira_em"],
                linha["user_agent"],
                linha["ip"],
            ),
        )
        await db.execute(
            """
            UPDATE sessoes
               SET revogada_em = CURRENT_TIMESTAMP,
                   motivo_revogacao = 'rotacao',
                   substituida_por = ?
             WHERE id = ?
            """,
            (nova_id, linha["id"]),
        )
        await db.commit()

    sessao = Sessao(
        id=nova_id,
        usuario=Usuario(
            id=linha["usuario_id"], username=linha["username"], papel=linha["papel"]
        ),
    )
    return sessao, novo_refresh


async def _derrubar_cadeia(sessao_id: str) -> None:
    """Revoga a sessão dada e todas que a sucederam. Chamada ao detectar reúso de refresh.

    Segue `substituida_por` para a frente porque é onde está a sessão que o atacante (ou o
    dono) está usando agora — revogar só o elo apresentado deixaria a cópia ativa viva, que
    é exatamente o que a detecção existe para impedir.
    """
    async with get_db() as db:
        atual: str | None = sessao_id
        # O limite é um cinto de segurança: `substituida_por` é uma cadeia linear, mas um
        # ciclo por dado corrompido travaria o processo aqui dentro.
        for _ in range(100):
            if atual is None:
                break
            cursor = await db.execute(
                "SELECT substituida_por FROM sessoes WHERE id = ?", (atual,)
            )
            linha = await cursor.fetchone()
            await db.execute(
                """
                UPDATE sessoes
                   SET revogada_em = COALESCE(revogada_em, CURRENT_TIMESTAMP),
                       motivo_revogacao = 'reuso_detectado'
                 WHERE id = ?
                """,
                (atual,),
            )
            atual = linha["substituida_por"] if linha else None
        await db.commit()


async def revogar(sessao_id: str, *, motivo: str) -> None:
    async with get_db() as db:
        await db.execute(
            """
            UPDATE sessoes
               SET revogada_em = CURRENT_TIMESTAMP, motivo_revogacao = ?
             WHERE id = ? AND revogada_em IS NULL
            """,
            (motivo, sessao_id),
        )
        await db.commit()


async def revogar_por_refresh(refresh: str, *, motivo: str) -> bool:
    """Encerra a sessão dona deste refresh. É o caminho do logout.

    Localizar pelo refresh, e não pelo access token, é o que faz sair funcionar com o access
    já vencido — que é exatamente quando a pessoa costuma clicar em sair.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            UPDATE sessoes
               SET revogada_em = CURRENT_TIMESTAMP, motivo_revogacao = ?
             WHERE refresh_hash = ? AND revogada_em IS NULL
            """,
            (motivo, hash_refresh(refresh)),
        )
        await db.commit()
        return cursor.rowcount > 0


async def revogar_todas(usuario_id: int, *, motivo: str) -> int:
    """Derruba todas as sessões abertas do usuário. Devolve quantas caíram."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            UPDATE sessoes
               SET revogada_em = CURRENT_TIMESTAMP, motivo_revogacao = ?
             WHERE usuario_id = ? AND revogada_em IS NULL
            """,
            (motivo, usuario_id),
        )
        await db.commit()
        return cursor.rowcount


# --------------------------------------------------------------------------- manutenção


async def avisar_credenciais_padrao() -> bool:
    """Grita no log da subida enquanto a conta de instalação continuar com a senha padrão.

    A migração 8 semeia admin/admin para que o primeiro login seja possível num banco novo.
    Essa senha está no código-fonte deste repositório: é pública. Deixá-la valendo em
    produção é o buraco mais banal que existe, e o mais fácil de esquecer aberto — a
    aplicação funciona perfeitamente, então nada denuncia o problema.

    Um bcrypt por subida, e nada além disso: bloquear a aplicação seria pior, porque quem
    ainda não trocou a senha ficaria sem como entrar para trocá-la.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT senha_hash FROM usuarios WHERE username = ?", (USUARIO_PADRAO,)
        )
        linha = await cursor.fetchone()

    if not linha or not verificar_senha(SENHA_PADRAO, linha["senha_hash"]):
        return False

    _log.warning(
        "SEGURANÇA: a conta '%s' ainda usa a senha padrão, que é pública no código-fonte. "
        "Troque agora: python -m scripts.criar_usuario renomear %s <nome> "
        "&& python -m scripts.criar_usuario senha <nome>",
        USUARIO_PADRAO,
        USUARIO_PADRAO,
    )
    return True


async def renomear_usuario(username_atual: str, username_novo: str) -> bool:
    """Troca o nome de acesso, preservando id, senha e a autoria já gravada.

    Existe para a conta de instalação virar a conta real sem criar uma segunda: `usuario_id`
    já aparece em `simulacoes` e `leituras_ocr`, e apagar a linha para recriá-la com outro
    nome quebraria essas referências ou deixaria o histórico órfão.
    """
    atual = normalizar_username(username_atual)
    novo = normalizar_username(username_novo)
    async with get_db() as db:
        cursor = await db.execute("SELECT id FROM usuarios WHERE username = ?", (atual,))
        if not await cursor.fetchone():
            return False
        # A checagem é só pela mensagem; quem garante é o UNIQUE COLLATE NOCASE da coluna.
        cursor = await db.execute("SELECT 1 FROM usuarios WHERE username = ?", (novo,))
        if await cursor.fetchone() and novo != atual:
            raise ValueError(f"Já existe um usuário com o nome '{novo}'.")
        await db.execute(
            "UPDATE usuarios SET username = ? WHERE username = ?", (novo, atual)
        )
        await db.commit()
    return True


async def purgar_sessoes(dias_de_carencia: int = 30) -> int:
    """Apaga sessões mortas há tempo suficiente para não interessarem mais.

    A carência existe por causa da detecção de reúso: uma sessão revogada por rotação ainda
    é útil enquanto o refresh que ela queimou puder reaparecer. Apagar cedo demais faria o
    reúso parecer um refresh desconhecido, e o ataque passaria como erro comum.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            DELETE FROM sessoes
             WHERE (revogada_em IS NOT NULL
                    AND revogada_em < datetime('now', ?))
                OR expira_em < datetime('now', ?)
            """,
            (f"-{int(dias_de_carencia)} days", f"-{int(dias_de_carencia)} days"),
        )
        await db.commit()
        return cursor.rowcount


# --------------------------------------------------------------------------- usuários


async def definir_senha(username: str, senha: str) -> bool:
    """Grava a senha nova e derruba as sessões abertas. False se o usuário não existe.

    Derrubar as sessões é o ponto: trocar a senha porque ela vazou não adianta nada se a
    sessão de quem a usou continuar de pé.
    """
    alvo = normalizar_username(username)
    async with get_db() as db:
        cursor = await db.execute("SELECT id FROM usuarios WHERE username = ?", (alvo,))
        linha = await cursor.fetchone()
        if not linha:
            return False
        await db.execute(
            """
            UPDATE usuarios
               SET senha_hash = ?, senha_atualizada_em = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (hash_senha(senha), linha["id"]),
        )
        await db.commit()

    await revogar_todas(linha["id"], motivo="senha_alterada")
    return True


async def criar_usuario(username: str, senha: str, *, papel: str = "operador") -> int:
    """Insere e devolve o id. Levanta `ValueError` se o username já existir.

    A checagem prévia é só para a mensagem: quem garante a unicidade é o UNIQUE COLLATE
    NOCASE da coluna, que também segura duas criações simultâneas.
    """
    alvo = normalizar_username(username)
    hash_novo = hash_senha(senha)
    async with get_db() as db:
        cursor = await db.execute("SELECT 1 FROM usuarios WHERE username = ?", (alvo,))
        if await cursor.fetchone():
            raise ValueError(f"Já existe um usuário com o nome '{alvo}'.")
        inserido = await db.execute(
            "INSERT INTO usuarios (username, senha_hash, papel) VALUES (?, ?, ?)",
            (alvo, hash_novo, papel),
        )
        await db.commit()
        return inserido.lastrowid
