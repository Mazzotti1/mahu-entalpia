"""Ponte entre o banco e o juiz: carregar o corpus rotulado, gravar o placar.

Nenhuma regra mora aqui. Quem decide o que é verdade e quem promove é `corpus_ocr`, que é
puro; este módulo só busca linhas e grava linhas. A separação existe porque a regra de
promoção é a parte que precisa ser exercitada com casos inventados, e ela não pode exigir
um banco para isso.
"""

from __future__ import annotations

from backend.database import get_db
from backend.services.afinador_ocr import (
    ObservacaoCampo,
    ObservacaoCaptura,
    ObservacaoLeitura,
)
from backend.services.corpus_ocr import (
    TOLERANCIA,
    CampoBruto,
    LeituraBruta,
    LeituraRotulada,
    Placar,
    rotular,
)


async def carregar_corpus() -> list[LeituraRotulada]:
    """Todas as leituras que fornecem verdade, já classificadas por camada.

    Traz o corpus inteiro de uma vez em vez de paginar: são leituras de painel industrial
    tiradas à mão, na casa das centenas por ano. Uma consulta e um dicionário resolvem, e
    qualquer coisa mais elaborada seria complexidade paga sem contrapartida.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, criado_em, imagem_arquivo, desfecho, ms_na_conferencia,
                   (avisos IS NOT NULL AND avisos != '[]') AS tem_aviso
              FROM leituras_ocr
             ORDER BY criado_em, id
            """
        )
        leituras = await cursor.fetchall()

        cursor = await db.execute(
            """
            SELECT leitura_id, key, pv_sugerido, pv_aplicado, status
              FROM leituras_ocr_campos
             ORDER BY leitura_id, key
            """
        )
        campos_por_leitura: dict[int, list[CampoBruto]] = {}
        for linha in await cursor.fetchall():
            campos_por_leitura.setdefault(linha["leitura_id"], []).append(
                CampoBruto(
                    key=linha["key"],
                    pv_sugerido=linha["pv_sugerido"],
                    pv_aplicado=linha["pv_aplicado"],
                    status=linha["status"],
                )
            )

    rotuladas = []
    for linha in leituras:
        bruta = LeituraBruta(
            id=linha["id"],
            criado_em=str(linha["criado_em"]),
            imagem_arquivo=linha["imagem_arquivo"],
            desfecho=linha["desfecho"],
            tem_aviso=bool(linha["tem_aviso"]),
            ms_na_conferencia=linha["ms_na_conferencia"],
            campos=tuple(campos_por_leitura.get(linha["id"], ())),
        )
        rotulada = rotular(bruta)
        if rotulada is not None:
            rotuladas.append(rotulada)

    return rotuladas


async def observacoes_do_treino(
    ids: list[int],
) -> tuple[dict[str, list[float]], list[ObservacaoCampo], list[ObservacaoLeitura]]:
    """O que o banco já sabe sobre um conjunto de leituras, no formato dos afinadores.

    Recebe os ids em vez de consultar o corpus inteiro porque a fatia de TREINO é o único
    recorte que o afinador pode enxergar. Deixá-lo ver o teste faria os parâmetros serem
    ajustados sobre as mesmas leituras que depois os julgam, e o placar passaria a medir
    memória em vez de acerto.

    `certo` compara sugerido com aplicado, e não com uma releitura: aqui interessa como o
    perfil VIGENTE se saiu na hora, que é o que descreve a distribuição de confiança que os
    limiares precisam separar.
    """
    if not ids:
        return {}, [], []

    marcadores = ",".join("?" * len(ids))

    async with get_db() as db:
        cursor = await db.execute(
            f"""
            SELECT leitura_id, key, pv_sugerido, pv_aplicado, confidence, status
              FROM leituras_ocr_campos
             WHERE leitura_id IN ({marcadores}) AND pv_aplicado IS NOT NULL
            """,
            ids,
        )
        linhas_campos = await cursor.fetchall()

        cursor = await db.execute(
            f"SELECT id, align_inliers FROM leituras_ocr WHERE id IN ({marcadores})",
            ids,
        )
        linhas_leituras = await cursor.fetchall()

    valores: dict[str, list[float]] = {}
    campos: list[ObservacaoCampo] = []
    errou: set[int] = set()

    for linha in linhas_campos:
        certo = (
            linha["pv_sugerido"] is not None
            and abs(linha["pv_sugerido"] - linha["pv_aplicado"]) <= TOLERANCIA
        )
        if not certo:
            errou.add(linha["leitura_id"])
        valores.setdefault(linha["key"], []).append(linha["pv_aplicado"])
        campos.append(
            ObservacaoCampo(
                key=linha["key"],
                pv_aplicado=linha["pv_aplicado"],
                confianca=linha["confidence"],
                status=linha["status"],
                certo=certo,
            )
        )

    leituras = [
        ObservacaoLeitura(inliers=linha["align_inliers"], teve_erro=linha["id"] in errou)
        for linha in linhas_leituras
    ]

    return valores, campos, leituras


async def observacoes_de_captura(ids: list[int]) -> list[ObservacaoCaptura]:
    """Como cada foto do treino chegou, e se ela deu certo.

    "Deu certo" é a leitura ter sido aplicada sem nenhum erro silencioso: um campo lido
    errado que se declarou `ok` é exatamente o que a foto boa não produz. Correção à mão
    não desqualifica a foto — o usuário viu o problema e resolveu, que é o fluxo funcionando.
    """
    if not ids:
        return []

    marcadores = ",".join("?" * len(ids))

    async with get_db() as db:
        cursor = await db.execute(
            f"""
            SELECT l.px_por_digito, l.nitidez, l.reflexo, l.inclinacao_graus,
                   l.align_erro_reproj_pior,
                   SUM(CASE WHEN c.status = 'ok'
                             AND (c.pv_sugerido IS NULL
                                  OR ABS(c.pv_sugerido - c.pv_aplicado) > 1e-6) THEN 1 ELSE 0 END)
                       AS silenciosos
              FROM leituras_ocr l
              JOIN leituras_ocr_campos c ON c.leitura_id = l.id
             WHERE l.id IN ({marcadores}) AND l.align_metodo IS NOT NULL
               AND c.pv_aplicado IS NOT NULL
             GROUP BY l.id
            """,
            ids,
        )
        linhas = await cursor.fetchall()

    return [
        ObservacaoCaptura(
            px_por_digito=linha["px_por_digito"],
            nitidez=linha["nitidez"],
            reflexo=linha["reflexo"],
            inclinacao_graus=linha["inclinacao_graus"],
            erro_reproj_pior=linha["align_erro_reproj_pior"],
            boa=(linha["silenciosos"] or 0) == 0,
        )
        for linha in linhas
    ]


async def gravar_avaliacao(
    *,
    corrida: str,
    perfil_id: int,
    papel: str,
    placar: Placar,
    decisao: str | None = None,
    motivo: str | None = None,
) -> int:
    """Grava o placar de um perfil numa corrida e devolve o id da avaliação."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO avaliacoes_ocr
                (corrida, perfil_id, papel, leituras, acertos, total, erros_silenciosos,
                 decisao, motivo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                corrida,
                perfil_id,
                papel,
                placar.leituras,
                placar.acertos,
                placar.total,
                placar.erros_silenciosos,
                decisao,
                motivo,
            ),
        )
        avaliacao_id = cursor.lastrowid

        await db.executemany(
            """
            INSERT INTO avaliacoes_ocr_campos
                (avaliacao_id, key, acertos, total, erros_silenciosos)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (avaliacao_id, key, campo.acertos, campo.total, campo.erros_silenciosos)
                for key, campo in sorted(placar.por_campo.items())
            ],
        )
        await db.commit()

    return avaliacao_id
