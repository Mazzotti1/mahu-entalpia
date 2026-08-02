#!/usr/bin/env python
"""Monta um perfil candidato a partir do corpus e manda o juiz decidir.

É o laço fechado: as leituras que os usuários aplicaram e corrigiram viram parâmetros, os
parâmetros viram um candidato, e o candidato só entra se ganhar do vigente sobre a fatia
mais recente do corpus — que o afinador nunca viu.

    # Propor, medir e promover se for melhor
    docker compose run --rm -v "$PWD/scripts:/scripts" backend python /scripts/afinar_ocr.py

    # Só ver o que seria proposto
    python /scripts/afinar_ocr.py --so-propor

    # Propor e medir, sem trocar nada
    python /scripts/afinar_ocr.py --simular

O afinador enxerga apenas a partição de TREINO. A de teste fica com o juiz, e é isso que
impede o sistema de se convencer sozinho: ajustar e medir no mesmo dado sempre "melhora".

Reprocessa as fotos do treino para saber onde os textos apareceram — é o que permite afinar
as ROIs. Com corpus grande isso leva minutos, como o avaliador.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import init_db  # noqa: E402
from backend.services.afinador_ocr import (  # noqa: E402
    CaixaObservada,
    afinar_limiares_captura,
    montar_candidato,
)
from backend.services.armazenamento_corpus import (  # noqa: E402
    carregar_corpus,
    observacoes_de_captura,
    observacoes_do_treino,
)
from backend.services.armazenamento_perfil import (  # noqa: E402
    carregar_perfil_ativo,
    gravar_candidato,
    gravar_limiares_captura,
    ler_limiares_captura,
)
from backend.services.corpus_ocr import (  # noqa: E402
    FRACAO_TESTE,
    TOLERANCIA,
    LeituraRotulada,
    particionar,
)
from backend.services.perfil_ocr import PerfilOCR  # noqa: E402
from backend.services.telemetria_ocr import MEDIA_DIR  # noqa: E402


def _caixas_do_treino(
    perfil: PerfilOCR, treino: list[LeituraRotulada]
) -> dict[str, list[CaixaObservada]]:
    """Onde cada campo apareceu no treino, marcando se aquela leitura saiu certa.

    As erradas vão junto, e não por descuido. Uma ROI deslocada faz o campo errar SEMPRE:
    filtrando por acerto, ele nunca teria evidência nenhuma e ficaria travado no erro que a
    ROI causou. O que salva esse caso é a posição da caixa em relação à borda do recorte, e
    para isso a leitura errada serve tão bem quanto a certa — o afinador é quem decide o que
    fazer com cada uma.
    """
    from backend.services.mahu_ocr import ler_mahu

    caixas: dict[str, list[CaixaObservada]] = {}

    for leitura in treino:
        caminho = os.path.join(MEDIA_DIR, leitura.imagem_arquivo)
        if not os.path.exists(caminho):
            continue
        with open(caminho, "rb") as arquivo:
            lido = ler_mahu(arquivo.read(), perfil)

        pv = {campo.key: campo.pv for campo in lido["campos"]}
        for campo in leitura.campos:
            caixa = lido["caixas"].get(campo.key)
            if caixa is None:
                continue
            valor = pv.get(campo.key)
            caixas.setdefault(campo.key, []).append(
                CaixaObservada(
                    caixa=caixa,
                    certo=valor is not None and abs(valor - campo.verdade) <= TOLERANCIA,
                )
            )

    return caixas


async def principal(argumentos: argparse.Namespace) -> int:
    await init_db()
    vigente = await carregar_perfil_ativo()

    corpus = await carregar_corpus()
    treino, teste = particionar(corpus, argumentos.fracao_teste)

    print("=" * 78)
    print(f"perfil vigente: {vigente.id}")
    print(f"corpus rotulado: {len(corpus)} leituras — {len(treino)} treino, {len(teste)} teste")

    if not treino:
        print("\nSem treino: o afinador não tem de onde tirar nada.")
        print("=" * 78)
        return 0

    valores, campos, leituras = await observacoes_do_treino([l.id for l in treino])
    caixas = {} if argumentos.sem_roi else _caixas_do_treino(vigente, treino)

    candidato = montar_candidato(
        vigente, valores=valores, campos=campos, leituras=leituras, caixas=caixas
    )

    # Os limiares do guia de câmera são afinados aqui e gravados na hora, sem passar pelo
    # juiz. Não é atalho: o juiz mede acerto sobre fotos JÁ tiradas, e mudar o guia não
    # altera nenhuma delas — todo candidato sairia "idêntico" e nada entraria nunca. O que
    # valida estes números é a taxa de descarte das fotos que chegarem depois.
    ids_treino = [leitura.id for leitura in treino]
    limiares, propostas_captura, silencio_captura = afinar_limiares_captura(
        await observacoes_de_captura(ids_treino), await ler_limiares_captura()
    )
    if limiares is not None and not argumentos.so_propor:
        await gravar_limiares_captura(limiares)
    for proposta in propostas_captura:
        print(f"\nGUIA DE CAPTURA ({proposta.amostras} fotos boas):")
        print(f"   {proposta.descricao}")
    for motivo in silencio_captura:
        print(f"\nGUIA DE CAPTURA: {motivo}")

    if candidato.silenciados:
        print("\nSEM AMOSTRA SUFICIENTE (o afinador se calou):")
        for motivo in candidato.silenciados:
            print(f"   {motivo}")

    if not candidato.mudou:
        print("\nNada a propor: o corpus concorda com o perfil vigente.")
        print("=" * 78)
        return 0

    print("\nPROPOSTAS:")
    for proposta in candidato.propostas:
        print(f"   {proposta.parametro:<22} {proposta.descricao}  ({proposta.amostras} amostras)")

    if argumentos.so_propor:
        print("\n(--so-propor: nada foi gravado)")
        print("=" * 78)
        return 0

    perfil_id = await gravar_candidato(candidato.perfil, derivado_de=vigente.id)
    print(f"\ncandidato gravado como perfil {perfil_id}")
    print("=" * 78)

    # Encadeia o juiz em vez de reimplementar a comparação: quem decide precisa ser um só,
    # senão passam a existir duas regras de promoção que divergem com o tempo.
    import avaliar_corpus

    return await avaliar_corpus.principal(
        argparse.Namespace(
            candidato=perfil_id,
            candidato_json=None,
            simular=argumentos.simular,
            fracao_teste=argumentos.fracao_teste,
            min_amostras=argumentos.min_amostras,
        )
    )


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analisador.add_argument(
        "--so-propor", action="store_true", help="mostra as propostas e para; não grava nada"
    )
    analisador.add_argument(
        "--simular", action="store_true", help="grava e mede o candidato, mas não o promove"
    )
    analisador.add_argument(
        "--sem-roi",
        action="store_true",
        help="pula o reprocessamento das fotos; afina só o que vem do banco",
    )
    analisador.add_argument("--fracao-teste", type=float, default=FRACAO_TESTE)
    analisador.add_argument("--min-amostras", type=int, default=30)
    return asyncio.run(principal(analisador.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
