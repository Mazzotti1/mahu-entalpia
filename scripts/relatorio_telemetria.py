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
