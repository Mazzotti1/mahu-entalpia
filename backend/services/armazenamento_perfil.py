"""Persistência dos perfis de OCR: semear, ler o ativo, gravar candidato, promover.

Separado de `perfil_ocr` pelo mesmo motivo de sempre por aqui: lá é a configuração como
valor, testável sem banco; aqui é o sqlite. Quem só precisa saber o que uma configuração
significa não deveria precisar de um banco para descobrir.
"""

from __future__ import annotations

from backend.database import get_db
from backend.services.guia_captura import LimiaresCaptura
from backend.services.perfil_ocr import (
    PERFIL_DO_CODIGO,
    PerfilOCR,
    de_json,
    definir_perfil_ativo,
)
from backend.services.vigilancia_ocr import Janela


async def carregar_perfil_ativo() -> PerfilOCR:
    """Semeia o perfil do código se não houver nenhum, e ativa o vigente no processo.

    Roda no boot. Semear é o que faz o primeiro perfil existir sem uma etapa manual: a
    linha 1 é literalmente o que o código já fazia, então o comportamento não muda no dia
    em que esta camada entra — muda a partir do dia em que alguém promove outra.

    Falha de leitura cai no perfil do código em vez de derrubar a API. Uma configuração
    corrompida no banco não pode impedir o app de ler painel: o pior caso aceitável é
    voltar ao comportamento do fonte, que é conhecido.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, config FROM perfis_ocr WHERE ativo = 1 LIMIT 1"
        )
        linha = await cursor.fetchone()

        if linha is None:
            cursor = await db.execute(
                """
                INSERT INTO perfis_ocr (config, ativo, origem)
                VALUES (?, 1, 'codigo')
                """,
                (PERFIL_DO_CODIGO.para_json(),),
            )
            await db.commit()
            perfil = PerfilOCR(id=cursor.lastrowid)
            definir_perfil_ativo(perfil)
            return perfil

    try:
        perfil = de_json(linha["config"], id=linha["id"])
    except (ValueError, TypeError):
        perfil = PERFIL_DO_CODIGO

    definir_perfil_ativo(perfil)
    return perfil


async def gravar_candidato(
    perfil: PerfilOCR,
    *,
    derivado_de: int | None,
    origem: str = "afinador",
    acerto: float | None = None,
    erros_silenciosos: int | None = None,
    amostras: int | None = None,
) -> int:
    """Grava um perfil SEM ativá-lo, e devolve o id.

    Gravar e promover são passos separados de propósito: o candidato precisa existir com id
    antes de ser medido, para que o resultado da medição possa apontar para ele. Fundir os
    dois faria toda configuração avaliada entrar em produção, que é exatamente o contrário
    do que o juiz existe para fazer.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO perfis_ocr
                (config, ativo, origem, derivado_de, acerto, erros_silenciosos, amostras)
            VALUES (?, 0, ?, ?, ?, ?, ?)
            """,
            (
                perfil.para_json(),
                origem,
                derivado_de,
                acerto,
                erros_silenciosos,
                amostras,
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def promover(perfil_id: int) -> PerfilOCR:
    """Torna `perfil_id` o ativo, e passa a servir por ele imediatamente.

    Desativar antes de ativar não é opcional: o índice único parcial recusa dois ativos, e
    a ordem inversa falharia. Os dois UPDATEs vão na mesma transação para que uma queda no
    meio não deixe o banco sem perfil ativo nenhum — estado em que o boot seguinte semearia
    um segundo perfil do código e o histórico passaria a apontar para configurações que
    ninguém escolheu.
    """
    async with get_db() as db:
        cursor = await db.execute("SELECT config FROM perfis_ocr WHERE id = ?", (perfil_id,))
        linha = await cursor.fetchone()
        if linha is None:
            raise ValueError(f"Perfil {perfil_id} não existe.")

        await db.execute("UPDATE perfis_ocr SET ativo = 0 WHERE ativo = 1")
        await db.execute("UPDATE perfis_ocr SET ativo = 1 WHERE id = ?", (perfil_id,))
        await db.commit()

    perfil = de_json(linha["config"], id=perfil_id)
    definir_perfil_ativo(perfil)
    return perfil


async def janelas_de_producao() -> tuple[Janela, Janela] | None:
    """Como o perfil vigente e o anterior se saíram em produção. `None` se não dá para comparar.

    Só leituras aplicadas ou corrigidas entram: é nelas que existe o par sugerido/aplicado,
    que é o que diz se o OCR errou. As pendentes e descartadas não têm veredito.

    O "anterior" é o perfil de onde o vigente derivou, e não simplesmente o de id menor: uma
    reversão cria um perfil novo, e comparar contra o vizinho numérico acabaria comparando
    contra o próprio rollback.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, derivado_de FROM perfis_ocr WHERE ativo = 1 LIMIT 1"
        )
        linha = await cursor.fetchone()
        if linha is None or linha["derivado_de"] is None:
            return None

        vigente_id, anterior_id = linha["id"], linha["derivado_de"]

        cursor = await db.execute(
            """
            SELECT l.perfil_id,
                   COUNT(DISTINCT l.id) AS leituras,
                   COUNT(c.key) AS campos,
                   SUM(CASE WHEN c.pv_sugerido IS NULL
                             OR ABS(c.pv_sugerido - c.pv_aplicado) > 1e-6 THEN 1 ELSE 0 END)
                       AS corrigidos,
                   SUM(CASE WHEN c.status = 'ok'
                             AND (c.pv_sugerido IS NULL
                                  OR ABS(c.pv_sugerido - c.pv_aplicado) > 1e-6) THEN 1 ELSE 0 END)
                       AS silenciosos
              FROM leituras_ocr l
              JOIN leituras_ocr_campos c ON c.leitura_id = l.id
             WHERE l.perfil_id IN (?, ?)
               AND l.desfecho IN ('aplicada', 'corrigida')
               AND c.pv_aplicado IS NOT NULL
             GROUP BY l.perfil_id
            """,
            (vigente_id, anterior_id),
        )
        por_perfil = {linha["perfil_id"]: linha for linha in await cursor.fetchall()}

    def janela(perfil_id: int) -> Janela:
        linha = por_perfil.get(perfil_id)
        if linha is None:
            return Janela(perfil_id, 0, 0, 0, 0)
        return Janela(
            perfil_id=perfil_id,
            leituras=linha["leituras"],
            campos=linha["campos"],
            corrigidos=linha["corrigidos"] or 0,
            silenciosos=linha["silenciosos"] or 0,
        )

    return janela(vigente_id), janela(anterior_id)


async def reverter(motivo: str) -> PerfilOCR | None:
    """Volta ao perfil de onde o vigente derivou e marca o vigente como revertido.

    Marcar importa tanto quanto voltar: sem `revertido_em`, o afinador montaria a mesma
    configuração no ciclo seguinte, ela venceria o mesmo conjunto de teste outra vez, e o
    sistema ficaria promovendo e revertendo em círculo.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, derivado_de FROM perfis_ocr WHERE ativo = 1 LIMIT 1"
        )
        linha = await cursor.fetchone()
        if linha is None or linha["derivado_de"] is None:
            return None

        ruim, alvo = linha["id"], linha["derivado_de"]
        cursor = await db.execute("SELECT config FROM perfis_ocr WHERE id = ?", (alvo,))
        destino = await cursor.fetchone()
        if destino is None:
            return None

        await db.execute(
            """
            UPDATE perfis_ocr
               SET ativo = 0, revertido_em = CURRENT_TIMESTAMP, motivo_reversao = ?
             WHERE id = ?
            """,
            (motivo, ruim),
        )
        await db.execute("UPDATE perfis_ocr SET ativo = 1 WHERE id = ?", (alvo,))
        await db.commit()

    perfil = de_json(destino["config"], id=alvo)
    definir_perfil_ativo(perfil)
    return perfil


async def configuracoes_revertidas() -> set[str]:
    """JSON das configurações que já foram revertidas.

    O juiz consulta para não repromover o que a produção já reprovou. Comparar o JSON
    inteiro, e não o id, porque o afinador monta um perfil NOVO a cada ciclo — o id é
    sempre diferente, a configuração é que se repete.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT config FROM perfis_ocr WHERE revertido_em IS NOT NULL"
        )
        return {linha["config"] for linha in await cursor.fetchall()}


async def ler_perfil(perfil_id: int) -> PerfilOCR | None:
    """Um perfil qualquer pelo id — o avaliador precisa disso para reler o campeão."""
    async with get_db() as db:
        cursor = await db.execute("SELECT config FROM perfis_ocr WHERE id = ?", (perfil_id,))
        linha = await cursor.fetchone()

    return None if linha is None else de_json(linha["config"], id=perfil_id)


# --- Limiares do guia de captura --------------------------------------------------------
# Ficam fora do `PerfilOCR` porque não passam pelo juiz, e não passam porque não podem: o
# juiz mede acerto sobre fotos JÁ TIRADAS, e mudar o limiar do guia não altera nenhuma
# delas. Todo candidato sairia "idêntico ao vigente" e nada entraria nunca. O que valida
# estes números é outra coisa — a taxa de descarte e de correção das fotos que chegam
# DEPOIS deles.


async def ler_limiares_captura() -> LimiaresCaptura:
    """Os limiares vigentes, ou os do código enquanto ninguém os derivou do corpus."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT px_por_digito_min, nitidez_min, reflexo_max, inclinacao_max,
                   erro_reproj_max, amostras
              FROM limiares_captura WHERE id = 1
            """
        )
        linha = await cursor.fetchone()

    if linha is None:
        return LimiaresCaptura()
    return LimiaresCaptura(
        px_por_digito_min=linha["px_por_digito_min"],
        nitidez_min=linha["nitidez_min"],
        reflexo_max=linha["reflexo_max"],
        inclinacao_max=linha["inclinacao_max"],
        erro_reproj_max=linha["erro_reproj_max"],
        amostras=linha["amostras"],
    )


async def gravar_limiares_captura(limiares: LimiaresCaptura) -> None:
    """Substitui a linha única. Sem histórico: o guia não precisa auditar o passado dele."""
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO limiares_captura
                (id, px_por_digito_min, nitidez_min, reflexo_max, inclinacao_max,
                 erro_reproj_max, amostras, atualizado_em)
            VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                px_por_digito_min = excluded.px_por_digito_min,
                nitidez_min = excluded.nitidez_min,
                reflexo_max = excluded.reflexo_max,
                inclinacao_max = excluded.inclinacao_max,
                erro_reproj_max = excluded.erro_reproj_max,
                amostras = excluded.amostras,
                atualizado_em = CURRENT_TIMESTAMP
            """,
            (
                limiares.px_por_digito_min,
                limiares.nitidez_min,
                limiares.reflexo_max,
                limiares.inclinacao_max,
                limiares.erro_reproj_max,
                limiares.amostras,
            ),
        )
        await db.commit()
