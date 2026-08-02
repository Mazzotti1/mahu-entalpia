#!/usr/bin/env python
"""Mede o OCR sobre o corpus que se acumula sozinho, e promove o que for melhor.

Diferente de `avaliar_ocr.py`, que roda sobre as mesmas 9 fotos com um ground truth escrito
à mão, este lê o que a produção já rotulou: toda leitura aplicada ou corrigida deixa o par
(sugerido, aplicado) no banco, e a foto fica no disco. O conjunto de teste cresce a cada uso
do app, sem ninguém montar nada.

    # Só medir o perfil vigente (é o que serve de gate no CI)
    docker compose run --rm -v "$PWD/scripts:/scripts" backend python /scripts/avaliar_corpus.py

    # Comparar um candidato com o vigente e promovê-lo se for melhor
    python /scripts/avaliar_corpus.py --candidato 7
    python /scripts/avaliar_corpus.py --candidato-json /scripts/candidato.json

    # Ver a decisão sem executá-la
    python /scripts/avaliar_corpus.py --candidato 7 --simular

Sai com 1 quando o perfil vigente produz erro silencioso — leitura errada com status `ok`,
que entra no cálculo sem passar por conferência. É o único resultado que reprova de fato.

O OCR leva segundos por foto em CPU, e comparar dois perfis relê o conjunto de teste duas
vezes. Com corpus grande isso é uma tarefa de minutos, não de segundos.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import init_db  # noqa: E402
from backend.services.armazenamento_corpus import carregar_corpus, gravar_avaliacao  # noqa: E402
from backend.services.armazenamento_perfil import (  # noqa: E402
    carregar_perfil_ativo,
    configuracoes_revertidas,
    gravar_candidato,
    janelas_de_producao,
    ler_perfil,
    promover,
    reverter,
)
from backend.services.corpus_ocr import (  # noqa: E402
    CAMADA_OURO,
    FRACAO_TESTE,
    MIN_AMOSTRAS_TESTE,
    LeituraRotulada,
    Placar,
    decidir,
    montar_placar,
    particionar,
)
from backend.services.perfil_ocr import PerfilOCR, de_json  # noqa: E402
from backend.services.telemetria_ocr import MEDIA_DIR  # noqa: E402
from backend.services.vigilancia_ocr import avaliar_janelas  # noqa: E402


def _ler_corpus_sob(
    perfil: PerfilOCR, leituras: list[LeituraRotulada]
) -> tuple[Placar, list[str]]:
    """Reprocessa cada foto sob `perfil` e monta o placar. Devolve também as fotos sumidas.

    Import tardio do OCR pelo mesmo motivo de `routes/pontos.py`: o módulo carrega OpenCV e
    torch, e quem só quer conferir os argumentos não deveria esperar por isso.
    """
    from backend.services.mahu_ocr import ler_mahu

    resultados = []
    ausentes = []

    for leitura in leituras:
        caminho = os.path.join(MEDIA_DIR, leitura.imagem_arquivo)
        if not os.path.exists(caminho):
            ausentes.append(leitura.imagem_arquivo)
            continue
        with open(caminho, "rb") as arquivo:
            lido = ler_mahu(arquivo.read(), perfil)
        resultados.append(
            (leitura, {campo.key: (campo.pv, campo.status) for campo in lido["campos"]})
        )

    return montar_placar(resultados), ausentes


def _mostrar_placar(titulo: str, perfil: PerfilOCR, placar: Placar) -> None:
    pct = 100.0 * placar.acertos / placar.total if placar.total else 0.0
    print(f"\n{titulo} (perfil {perfil.id})")
    print(
        f"   {placar.acertos}/{placar.total} campos ({pct:.1f}%) em {placar.leituras} leituras"
        f" | erros silenciosos: {placar.erros_silenciosos}"
    )
    print(f"   {'campo':<22}{'acerto':>14}{'silencioso':>13}")
    for key, campo in sorted(
        placar.por_campo.items(), key=lambda item: item[1].acertos / max(item[1].total, 1)
    ):
        parcial = f"{campo.acertos}/{campo.total} ({100.0 * campo.acertos / campo.total:.0f}%)"
        print(f"   {key:<22}{parcial:>14}{campo.erros_silenciosos:>13}")


async def _vigiar(argumentos: argparse.Namespace) -> None:
    """Confere se a promoção anterior azedou em produção, e desfaz se azedou.

    Roda no início de toda corrida do juiz, e não num processo separado: quem já vai medir o
    OCR é o lugar natural para perguntar antes se o que está no ar ainda merece estar. Um
    agendador a mais para manter não se paga.
    """
    janelas = await janelas_de_producao()
    if janelas is None:
        return

    novo, anterior = janelas
    vigilancia = avaliar_janelas(novo, anterior)
    print(
        f"\nVIGILÂNCIA: perfil {novo.perfil_id} com {novo.leituras} leituras "
        f"({100 * novo.taxa_erro:.1f}% de correção) contra perfil {anterior.perfil_id} "
        f"com {anterior.leituras} ({100 * anterior.taxa_erro:.1f}%)"
    )
    print(f"   {vigilancia.motivo}")

    if not vigilancia.reverter:
        return
    if argumentos.simular:
        print("   (--simular: reversão não executada)")
        return

    revertido = await reverter(vigilancia.motivo)
    if revertido is not None:
        print(f"   REVERTIDO para o perfil {revertido.id}.")


async def principal(argumentos: argparse.Namespace) -> int:
    await init_db()
    await carregar_perfil_ativo()
    await _vigiar(argumentos)
    # Relê depois da vigilância: uma reversão troca o vigente, e medir o perfil que acabou
    # de sair do ar não diria nada sobre o que está servindo agora.
    campeao = await carregar_perfil_ativo()

    corpus = await carregar_corpus()
    treino, teste = particionar(corpus, argumentos.fracao_teste)

    ouro = sum(1 for leitura in corpus for campo in leitura.campos if campo.camada == CAMADA_OURO)
    total_campos = sum(len(leitura.campos) for leitura in corpus)

    print("=" * 78)
    print(f"corpus rotulado: {len(corpus)} leituras, {total_campos} campos ({ouro} de ouro)")
    print(f"partição temporal: {len(treino)} para treino, {len(teste)} para teste")

    if not teste:
        print("\nCorpus vazio — nada a medir. Use o app: cada leitura aplicada vira teste.")
        print("=" * 78)
        return 0

    # Com resolução de segundo, duas corridas seguidas colidiriam e as linhas do campeão de
    # uma apareceriam agrupadas com o candidato da outra — que é exatamente o que a coluna
    # existe para impedir.
    corrida = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    placar_campeao, ausentes = _ler_corpus_sob(campeao, teste)
    if ausentes:
        print(f"\n{len(ausentes)} foto(s) do corpus sumiram do disco e ficaram de fora.")

    _mostrar_placar("VIGENTE", campeao, placar_campeao)
    await gravar_avaliacao(
        corrida=corrida, perfil_id=campeao.id, papel="campeao", placar=placar_campeao
    )

    candidato = await _resolver_candidato(argumentos, campeao)
    if candidato is None:
        print("\nSem candidato: nada a promover.")
        print("=" * 78)
        # Erro silencioso do vigente é o que reprova: leitura errada que se declarou boa.
        return 1 if placar_campeao.erros_silenciosos else 0

    placar_candidato, _ = _ler_corpus_sob(candidato, teste)
    _mostrar_placar("CANDIDATO", candidato, placar_candidato)

    decisao = decidir(
        placar_campeao,
        placar_candidato,
        min_amostras=argumentos.min_amostras,
    )

    # A produção tem a última palavra sobre o conjunto de teste. Uma configuração que já foi
    # revertida vence o mesmo teste de novo — os dados não mudaram — e sem esta checagem o
    # sistema promoveria e reverteria a mesma coisa em círculo.
    if decisao.promover and candidato.para_json() in await configuracoes_revertidas():
        decisao = replace(
            decisao,
            promover=False,
            motivo="configuração idêntica a uma que já foi revertida em produção",
        )

    print("\nDECISÃO:")
    print(f"   discordâncias: candidato {decisao.so_candidato} x {decisao.so_campeao} vigente")
    print(f"   {'PROMOVER' if decisao.promover else 'MANTER O VIGENTE'} — {decisao.motivo}")

    # Três estados, e não dois: em `--simular` o candidato pode ter VENCIDO e mesmo assim
    # não ter entrado. Gravar isso como 'recusado' deixaria no banco uma linha que diz
    # "recusado" com o motivo "melhor em 6 campos e pior em 0" — contraditória, e do tipo
    # que faz alguém desconfiar do juiz meses depois sem entender por quê.
    if not decisao.promover:
        veredito = "recusado"
    elif argumentos.simular:
        veredito = "simulado"
    else:
        veredito = "promovido"

    await gravar_avaliacao(
        corrida=corrida,
        perfil_id=candidato.id,
        papel="candidato",
        placar=placar_candidato,
        decisao=veredito,
        motivo=decisao.motivo,
    )

    if decisao.promover and argumentos.simular:
        print("   (--simular: promoção não executada)")
    elif decisao.promover:
        await promover(candidato.id)
        print(f"   perfil {candidato.id} agora é o vigente.")

    print("=" * 78)
    return 1 if placar_campeao.erros_silenciosos else 0


async def _resolver_candidato(
    argumentos: argparse.Namespace, campeao: PerfilOCR
) -> PerfilOCR | None:
    """O candidato vem do banco por id, ou de um JSON que é gravado como perfil novo.

    O JSON precisa virar linha antes de ser julgado: o placar aponta para um `perfil_id`, e
    sem ele a avaliação ficaria pendurada em nada. É também o que permite reencontrar depois
    a configuração exata que foi recusada.
    """
    if argumentos.candidato is not None:
        perfil = await ler_perfil(argumentos.candidato)
        if perfil is None:
            print(f"Perfil {argumentos.candidato} não existe.", file=sys.stderr)
            raise SystemExit(2)
        return perfil

    if argumentos.candidato_json is None:
        return None

    with open(argumentos.candidato_json, encoding="utf-8") as arquivo:
        perfil = de_json(arquivo.read())
    perfil_id = await gravar_candidato(perfil, derivado_de=campeao.id, origem="arquivo")
    print(f"candidato de {argumentos.candidato_json} gravado como perfil {perfil_id}")
    return await ler_perfil(perfil_id)


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    grupo = analisador.add_mutually_exclusive_group()
    grupo.add_argument("--candidato", type=int, help="id de um perfil já gravado")
    grupo.add_argument("--candidato-json", help="arquivo com a configuração a testar")
    analisador.add_argument(
        "--simular",
        action="store_true",
        help="decide e grava o placar, mas não troca o perfil vigente",
    )
    analisador.add_argument("--fracao-teste", type=float, default=FRACAO_TESTE)
    analisador.add_argument("--min-amostras", type=int, default=MIN_AMOSTRAS_TESTE)
    return asyncio.run(principal(analisador.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
