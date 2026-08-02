#!/usr/bin/env python
"""Acerto do OCR medido contra as correções que os usuários fizeram em produção.

Diferente de `avaliar_ocr.py`, que precisa de um ground truth escrito à mão para um punhado
de fotos, este lê o corpus que se acumula sozinho: toda vez que alguém aplica uma leitura,
o par (sugerido, aplicado) fica gravado. Divergência = erro de OCR rotulado.

    python scripts/relatorio_telemetria.py [caminho/do/simulador.db]

Sem argumento usa CARTA_DB_PATH, ou backend/simulador.db.
"""

from __future__ import annotations

import os
import sqlite3
import sys

CAMINHO_PADRAO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "simulador.db"
)


# Abaixo disso, aplicar sem corrigir nada não é evidência de que a leitura estava certa:
# ninguém lê seis campos em menos de dois segundos. Foi assim que a leitura #28 entrou no
# banco com quatro campos corrompidos e confiança alta em todos.
MS_CARIMBO = 2000


def _tem_colunas_de_captura(conexao: sqlite3.Connection) -> bool:
    return "desfecho" in {linha[1] for linha in conexao.execute("PRAGMA table_info(leituras_ocr)")}


def _desfechos(conexao: sqlite3.Connection) -> None:
    """O que aconteceu com cada leitura, e quantas viraram rótulo forte.

    'descartada' é o exemplo negativo de captura, e 'corrigida' o positivo de erro do OCR.
    As aplicadas em menos de `MS_CARIMBO` ficam à parte porque não são conferência: entram
    no corpus com peso menor, ou não entram.
    """
    if not _tem_colunas_de_captura(conexao):
        print("\n(sem colunas de captura — banco anterior à migração 4)")
        return

    print("\nDESFECHO DAS LEITURAS:")
    for linha in conexao.execute(
        "SELECT desfecho, COUNT(*) AS n FROM leituras_ocr GROUP BY desfecho ORDER BY n DESC"
    ):
        print(f"   {linha['desfecho']:<20} {linha['n']}")

    motivos = conexao.execute(
        """
        SELECT motivo_descarte, COUNT(*) AS n FROM leituras_ocr
         WHERE motivo_descarte IS NOT NULL GROUP BY motivo_descarte ORDER BY n DESC
        """
    ).fetchall()
    if motivos:
        print("   motivos do descarte:")
        for linha in motivos:
            print(f"      {linha['motivo_descarte']:<17} {linha['n']}")

    carimbos = conexao.execute(
        """
        SELECT COUNT(*) AS n FROM leituras_ocr
         WHERE desfecho = 'aplicada' AND ms_na_conferencia IS NOT NULL
           AND ms_na_conferencia < ?
        """,
        (MS_CARIMBO,),
    ).fetchone()["n"]
    preservadas = conexao.execute(
        "SELECT COUNT(*) AS n FROM leituras_ocr WHERE preservar = 1"
    ).fetchone()["n"]
    print(f"   aplicadas em menos de {MS_CARIMBO} ms (carimbo, não conferência): {carimbos}")
    print(f"   imagens preservadas da purga (corpus rotulado): {preservadas}")


def _qualidade_da_captura(conexao: sqlite3.Connection) -> None:
    """Como as fotos chegaram, separadas por desfecho.

    É a comparação que interessa: se as descartadas têm nitidez menor e erro de reprojeção
    maior que as aplicadas, os limiares do pré-voo saem daí em vez de serem chutados.
    """
    if not _tem_colunas_de_captura(conexao):
        return

    # Média, e não mediana: o SQLite não tem mediana embutida e fazê-la aqui exigiria
    # trazer todas as linhas para a memória. Com o corpus ainda pequeno a média já mostra a
    # separação; quando o avaliador da Fase 1 existir, ele calcula os quantis direito.
    print("\nQUALIDADE DA CAPTURA, POR DESFECHO (média):")
    print(
        f"   {'desfecho':<14}{'n':>4}{'inliers':>9}{'reproj':>8}{'pior':>7}"
        f"{'nitidez':>9}{'reflexo':>9}{'incl':>7}{'px/díg':>8}"
    )
    linhas = conexao.execute(
        """
        SELECT desfecho, COUNT(*) AS n,
               AVG(align_inliers) AS inliers, AVG(align_erro_reproj) AS reproj,
               AVG(align_erro_reproj_pior) AS pior, AVG(nitidez) AS nitidez,
               AVG(reflexo) AS reflexo, AVG(inclinacao_graus) AS incl,
               AVG(px_por_digito) AS px
          FROM leituras_ocr
         WHERE align_metodo IS NOT NULL
         GROUP BY desfecho ORDER BY n DESC
        """
    ).fetchall()

    if not linhas:
        print("   (nenhuma leitura com métricas ainda — só as gravadas após a migração 4)")
        return

    def numero(valor, casas=2):
        return "-" if valor is None else f"{valor:.{casas}f}"

    for linha in linhas:
        print(
            f"   {linha['desfecho']:<14}{linha['n']:>4}{numero(linha['inliers'], 0):>9}"
            f"{numero(linha['reproj']):>8}{numero(linha['pior']):>7}"
            f"{numero(linha['nitidez'], 0):>9}{numero(linha['reflexo'], 4):>9}"
            f"{numero(linha['incl'], 1):>7}{numero(linha['px'], 1):>8}"
        )

    print("\n   MÉTODO DE ALINHAMENTO (cair fora de 'homografia' já é sinal de foto ruim):")
    for linha in conexao.execute(
        """
        SELECT align_metodo, COUNT(*) AS n FROM leituras_ocr
         WHERE align_metodo IS NOT NULL GROUP BY align_metodo ORDER BY n DESC
        """
    ):
        print(f"      {linha['align_metodo']:<17} {linha['n']}")


def _perfis(conexao: sqlite3.Connection) -> None:
    """Qual configuração leu o quê, e com que placar ela entrou.

    O acerto por campo mais abaixo mistura todas as leituras. Quando houver mais de um
    perfil no histórico, essa mistura passa a comparar coisas diferentes — daí a contagem
    por perfil: ela diz se um número mudou porque o OCR melhorou ou só porque a
    configuração trocou no meio.
    """
    tabelas = {
        linha["name"] for linha in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "perfis_ocr" not in tabelas:
        return

    linhas = conexao.execute(
        """
        SELECT p.id, p.ativo, p.origem, p.derivado_de, p.acerto, p.erros_silenciosos,
               p.amostras, COUNT(l.id) AS leituras
          FROM perfis_ocr p
          LEFT JOIN leituras_ocr l ON l.perfil_id = p.id
         GROUP BY p.id ORDER BY p.id
        """
    ).fetchall()
    if not linhas:
        return

    print("\nPERFIS DE OCR:")
    print(f"   {'id':>3} {'':<2}{'origem':<11}{'de':>4}{'leituras':>10}{'acerto':>9}{'silenc.':>9}{'amostras':>10}")
    for linha in linhas:
        acerto = "-" if linha["acerto"] is None else f"{100.0 * linha['acerto']:.1f}%"
        print(
            f"   {linha['id']:>3} {'*' if linha['ativo'] else ' ':<2}{linha['origem']:<11}"
            f"{linha['derivado_de'] if linha['derivado_de'] is not None else '-':>4}"
            f"{linha['leituras']:>10}{acerto:>9}"
            f"{linha['erros_silenciosos'] if linha['erros_silenciosos'] is not None else '-':>9}"
            f"{linha['amostras'] if linha['amostras'] is not None else '-':>10}"
        )

    orfas = conexao.execute(
        "SELECT COUNT(*) AS n FROM leituras_ocr WHERE perfil_id IS NULL"
    ).fetchone()["n"]
    if orfas:
        print(f"   {orfas} leitura(s) sem perfil — gravadas antes da migração 5")


def _avaliacoes(conexao: sqlite3.Connection, limite: int = 12) -> None:
    """As últimas corridas do avaliador: acurácia ao longo do tempo e o que foi recusado.

    É a série temporal que o acerto por campo mais abaixo não dá. Aquele número mistura
    tudo que já foi lido; este diz se o conjunto de teste vem sendo lido melhor ou pior a
    cada corrida — e, quando um candidato não entrou, por quê.
    """
    tabelas = {
        linha["name"] for linha in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "avaliacoes_ocr" not in tabelas:
        return

    linhas = conexao.execute(
        """
        SELECT criado_em, perfil_id, papel, acertos, total, erros_silenciosos, decisao, motivo
          FROM avaliacoes_ocr ORDER BY id DESC LIMIT ?
        """,
        (limite,),
    ).fetchall()
    if not linhas:
        return

    print("\nÚLTIMAS AVALIAÇÕES (scripts/avaliar_corpus.py):")
    for linha in reversed(linhas):
        pct = 100.0 * linha["acertos"] / linha["total"] if linha["total"] else 0.0
        veredito = f" [{linha['decisao']}] {linha['motivo']}" if linha["decisao"] else ""
        print(
            f"   {str(linha['criado_em'])[:19]}  perfil {linha['perfil_id']:<3} "
            f"{linha['papel']:<10}{linha['acertos']}/{linha['total']} ({pct:.1f}%)  "
            f"silenciosos={linha['erros_silenciosos']}{veredito}"
        )


def main(db_path: str) -> int:
    if not os.path.exists(db_path):
        print(f"Banco não encontrado: {db_path}", file=sys.stderr)
        return 2

    conexao = sqlite3.connect(db_path)
    conexao.row_factory = sqlite3.Row

    tabelas = {
        linha["name"] for linha in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "leituras_ocr_campos" not in tabelas:
        print("Este banco ainda não tem telemetria de OCR (migração 2).", file=sys.stderr)
        return 2

    total_leituras = conexao.execute("SELECT COUNT(*) AS n FROM leituras_ocr").fetchone()["n"]
    aplicadas = conexao.execute(
        "SELECT COUNT(DISTINCT leitura_id) AS n FROM leituras_ocr_campos WHERE pv_aplicado IS NOT NULL"
    ).fetchone()["n"]

    print("=" * 78)
    print(f"banco: {db_path}")
    print(f"leituras registradas: {total_leituras} | aplicadas pelo usuário: {aplicadas}")

    # Antes do corte por "aplicadas": leitura descartada nunca é aplicada, e é justamente
    # ela que descreve a foto ruim. Sair aqui esconderia o único exemplo negativo do corpus.
    _desfechos(conexao)
    _qualidade_da_captura(conexao)
    _perfis(conexao)
    _avaliacoes(conexao)

    if aplicadas == 0:
        print("\nNenhuma leitura aplicada ainda — sem par sugerido/aplicado para medir.")
        print("=" * 78)
        return 0

    origens = conexao.execute(
        "SELECT origem, COUNT(*) AS n FROM simulacoes GROUP BY origem ORDER BY n DESC"
    ).fetchall()
    print("\nPROCEDÊNCIA DAS SIMULAÇÕES:")
    for linha in origens:
        print(f"   {linha['origem']:<20} {linha['n']}")

    print("\nACERTO POR CAMPO (sugerido == aplicado):")
    linhas = conexao.execute(
        """
        SELECT key,
               COUNT(*) AS total,
               SUM(CASE WHEN pv_sugerido IS NOT NULL
                         AND ABS(pv_sugerido - pv_aplicado) < 1e-6 THEN 1 ELSE 0 END) AS certos,
               SUM(CASE WHEN status = 'ok'
                         AND (pv_sugerido IS NULL
                              OR ABS(pv_sugerido - pv_aplicado) >= 1e-6) THEN 1 ELSE 0 END)
                   AS silenciosos,
               AVG(confidence) AS confianca
        FROM leituras_ocr_campos
        WHERE pv_aplicado IS NOT NULL
        GROUP BY key
        ORDER BY (1.0 * certos / total)
        """
    ).fetchall()

    print(f"   {'campo':<22}{'acerto':>12}{'silencioso':>13}{'confiança':>12}")
    for linha in linhas:
        pct = 100.0 * linha["certos"] / linha["total"]
        confianca = f"{linha['confianca']:.2f}" if linha["confianca"] is not None else "-"
        alerta = "  <-- pior" if linha is linhas[0] and pct < 100 else ""
        print(
            f"   {linha['key']:<22}"
            f"{f'{linha['certos']}/{linha['total']} ({pct:.0f}%)':>12}"
            f"{linha['silenciosos']:>13}"
            f"{confianca:>12}{alerta}"
        )

    print("\nCORREÇÕES MAIS RECENTES (o que o OCR errou):")
    correcoes = conexao.execute(
        """
        SELECT c.leitura_id, c.key, c.raw_text, c.pv_sugerido, c.pv_aplicado, c.status, c.motivo
        FROM leituras_ocr_campos c
        WHERE c.pv_aplicado IS NOT NULL
          AND (c.pv_sugerido IS NULL OR ABS(c.pv_sugerido - c.pv_aplicado) >= 1e-6)
        ORDER BY c.leitura_id DESC
        LIMIT 25
        """
    ).fetchall()

    if not correcoes:
        print("   nenhuma — o OCR acertou tudo que foi aplicado")
    for linha in correcoes:
        motivo = f" [{linha['motivo']}]" if linha["motivo"] else ""
        print(
            f"   #{linha['leitura_id']:<5} {linha['key']:<20} "
            f"leu {str(linha['pv_sugerido']):>8} -> aplicado {linha['pv_aplicado']:>8} "
            f"({linha['status']}{motivo}, raw={linha['raw_text']!r})"
        )

    print("\nLEITURAS COM AVISO DA VALIDAÇÃO CRUZADA:")
    com_aviso = conexao.execute(
        "SELECT COUNT(*) AS n FROM leituras_ocr WHERE avisos IS NOT NULL AND avisos != '[]'"
    ).fetchone()["n"]
    print(f"   {com_aviso} de {total_leituras}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    caminho = (
        sys.argv[1] if len(sys.argv) > 1 else os.getenv("CARTA_DB_PATH") or CAMINHO_PADRAO
    )
    raise SystemExit(main(caminho))
