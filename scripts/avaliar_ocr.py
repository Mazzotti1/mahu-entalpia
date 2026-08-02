#!/usr/bin/env python
"""Mede a acurácia do OCR do MAHU contra um conjunto de fotos com valores conhecidos.

Uso (sem precisar rebuildar a imagem, montando as pastas no container):

    docker compose run --rm \
        -v "$PWD/docs:/docs" -v "$PWD/scripts:/scripts" \
        backend python /scripts/avaliar_ocr.py /docs/fotosMahu

O diretório precisa conter um ground_truth.json mapeando arquivo -> {campo: valor},
com null nos campos que não aparecem no enquadramento.

O número que importa não é só quantos campos acertou: é quantos ERROS SILENCIOSOS
existem — leituras erradas com status "ok", que entram no cálculo sem passar pela
conferência manual. Esse número precisa ser zero.
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, "/app")

from backend.services.mahu_campos import CAMPOS_OBRIGATORIOS  # noqa: E402
from backend.services.mahu_ocr import ler_mahu  # noqa: E402
from backend.services.mahu_validacao import validar_leitura  # noqa: E402

OBRIGATORIOS = CAMPOS_OBRIGATORIOS


def main(diretorio: str) -> int:
    caminho_gt = os.path.join(diretorio, "ground_truth.json")
    if not os.path.exists(caminho_gt):
        print(f"ground_truth.json não encontrado em {diretorio}", file=sys.stderr)
        return 2

    with open(caminho_gt, encoding="utf-8") as arquivo:
        ground_truth = {k: v for k, v in json.load(arquivo).items() if not k.startswith("_")}

    print("=" * 104)
    print(f"{'foto':<10}{'seg':<7}{'review':<9}" + "".join(f"{k:>13}" for k in OBRIGATORIOS))
    print("=" * 104)

    acertos = total = 0
    silenciosos: list[str] = []
    # Acerto por campo: a média global esconde o campo que sempre erra, e é justamente ele
    # que precisa de ROI nova ou de outra variante de pré-processamento.
    por_campo: dict[str, list[int]] = {key: [] for key in OBRIGATORIOS}

    for nome in sorted(ground_truth):
        caminho = os.path.join(diretorio, nome)
        if not os.path.exists(caminho):
            print(f"{nome:<10} (arquivo ausente)")
            continue

        with open(caminho, "rb") as imagem:
            inicio = time.perf_counter()
            resultado = ler_mahu(imagem.read())
            duracao = time.perf_counter() - inicio

        campos = {campo.key: campo for campo in resultado["campos"]}
        avisos = validar_leitura(resultado["valores"])
        review = any(
            campo.obrigatorio and campo.status != "ok" for campo in resultado["campos"]
        ) or bool(avisos)

        linha = f"{nome:<10}{duracao:<7.2f}{str(review):<9}"
        esperados = f"{'':<10}{'':<7}{'esperado':<9}"

        for key in OBRIGATORIOS:
            campo = campos[key]
            esperado = ground_truth[nome].get(key)
            certo = campo.pv == esperado
            if esperado is not None:
                total += 1
                acertos += certo
                por_campo[key].append(int(certo))
            if not certo and campo.status == "ok":
                silenciosos.append(f"{nome}/{key}: leu {campo.pv}, esperado {esperado}")
            linha += f"{str(campo.pv) + ('.' if certo else 'X'):>13}"
            esperados += f"{str(esperado):>13}"

        print(linha)
        print(esperados)
        for aviso in avisos:
            print(f"{'':<26}aviso: {aviso.mensagem}")
        print("-" * 104)

    pct = 100.0 * acertos / total if total else 0.0
    print(f"ACERTOS: {acertos}/{total} ({pct:.0f}%)")
    print("\nPOR CAMPO:")
    for key in OBRIGATORIOS:
        marcas = por_campo[key]
        if not marcas:
            print(f"   {key:<22} (sem ground truth)")
            continue
        print(
            f"   {key:<22} {sum(marcas)}/{len(marcas)} "
            f"({100.0 * sum(marcas) / len(marcas):.0f}%)"
        )

    print(f"\nERROS SILENCIOSOS (status 'ok' com valor errado): {len(silenciosos)}")
    for erro in silenciosos:
        print(f"   ! {erro}")
    print("=" * 104)

    # Erro silencioso é o único resultado que reprova de fato.
    return 1 if silenciosos else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
