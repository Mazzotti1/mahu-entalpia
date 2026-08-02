"""Persistência das leituras de OCR: o que foi sugerido, o que foi aplicado, e a foto.

Existe por causa de uma lacuna simples: o banco guardava só o resultado aceito. `raw_text`,
confiança e status eram calculados, mandados ao navegador e descartados, e não havia registro
de quais leituras o usuário tinha corrigido à mão. Cada correção dessas é um erro de OCR
rotulado de graça — é o único ground truth que escala, e estava indo para o lixo.

Guardar a imagem é o que permite reprocessar leituras antigas com um OCR melhorado e
comparar, em vez de só torcer.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict

from backend.database import DB_PATH, get_db
from backend.models import MahuCampoOCR
from backend.services.mahu_validacao import Aviso, LeituraAnterior

# Ao lado do banco por padrão: em container o CARTA_DB_PATH aponta para /data, que já é
# volume, então as fotos herdam a mesma persistência sem mexer no compose.
MEDIA_DIR = os.getenv("CARTA_MEDIA_DIR") or os.path.join(os.path.dirname(DB_PATH), "media")

# Guardar foto de painel industrial é barato e útil, mas é decisão de quem opera.
GUARDAR_IMAGENS = os.getenv("CARTA_GUARDAR_IMAGENS", "1") != "0"

# 0 desliga a purga e mantém tudo.
RETENCAO_DIAS = int(os.getenv("CARTA_MEDIA_RETENCAO_DIAS", "90"))

_ASSINATURAS = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"RIFF", ".webp"),
)


def _extensao(image_bytes: bytes) -> str:
    for assinatura, extensao in _ASSINATURAS:
        if image_bytes.startswith(assinatura):
            return extensao
    return ".bin"


async def registrar_leitura(
    campos: list[MahuCampoOCR],
    *,
    requires_review: bool,
    avisos: list[Aviso],
    image_bytes: bytes,
) -> int:
    """Grava a leitura e devolve o id que o frontend devolve ao aplicar."""
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO leituras_ocr (imagem_sha256, imagem_bytes, requires_review, avisos)
            VALUES (?, ?, ?, ?)
            """,
            (
                hashlib.sha256(image_bytes).hexdigest(),
                len(image_bytes),
                int(requires_review),
                json.dumps([asdict(aviso) for aviso in avisos], ensure_ascii=False),
            ),
        )
        leitura_id = cursor.lastrowid

        await db.executemany(
            """
            INSERT INTO leituras_ocr_campos
                (leitura_id, key, raw_text, pv_sugerido, confidence, status, motivo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    leitura_id,
                    campo.key,
                    campo.raw_text,
                    campo.pv,
                    campo.confidence,
                    campo.status,
                    campo.motivo,
                )
                for campo in campos
            ],
        )

        # O arquivo é nomeado pelo id, então a gravação vem depois do INSERT. Falha de
        # disco não pode derrubar a leitura: a telemetria é subproduto, não o serviço.
        arquivo = _gravar_imagem(leitura_id, image_bytes)
        if arquivo:
            await db.execute(
                "UPDATE leituras_ocr SET imagem_arquivo = ? WHERE id = ?", (arquivo, leitura_id)
            )

        await db.commit()

    return leitura_id


def _gravar_imagem(leitura_id: int, image_bytes: bytes) -> str | None:
    if not GUARDAR_IMAGENS:
        return None
    try:
        os.makedirs(MEDIA_DIR, exist_ok=True)
        arquivo = f"{leitura_id}{_extensao(image_bytes)}"
        with open(os.path.join(MEDIA_DIR, arquivo), "wb") as destino:
            destino.write(image_bytes)
        return arquivo
    except OSError:
        return None


async def registrar_aplicacao(leitura_id: int, aplicados: dict[str, float]) -> str:
    """Anota o que o usuário de fato aplicou e devolve a origem da simulação.

    'ocr_corrigida' quando algum campo saiu diferente do sugerido — é essa divergência que
    o avaliador usa como rótulo.
    """
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT key, pv_sugerido FROM leituras_ocr_campos WHERE leitura_id = ?",
            (leitura_id,),
        )
        sugeridos = {linha["key"]: linha["pv_sugerido"] for linha in await cursor.fetchall()}
        if not sugeridos:
            return "manual"

        await db.executemany(
            "UPDATE leituras_ocr_campos SET pv_aplicado = ? WHERE leitura_id = ? AND key = ?",
            [(valor, leitura_id, key) for key, valor in aplicados.items()],
        )
        await db.commit()

    # Comparação em ponto flutuante com tolerância da resolução do display: o valor volta
    # do navegador como texto e pode reaparecer como 11.800000000000001.
    corrigida = any(
        sugeridos.get(key) is None or abs(sugeridos[key] - valor) > 1e-6
        for key, valor in aplicados.items()
    )
    return "ocr_corrigida" if corrigida else "ocr_conferida"


async def ultima_leitura_aplicada() -> LeituraAnterior | None:
    """Última leitura confirmada pelo usuário, para o validador de continuidade.

    Usa `pv_aplicado` e não `pv_sugerido`: comparar contra o que alguém conferiu evita
    acusar a leitura nova por causa de um erro na anterior.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, (julianday('now') - julianday(criado_em)) * 1440.0 AS minutos
            FROM leituras_ocr
            WHERE id IN (SELECT leitura_id FROM leituras_ocr_campos WHERE pv_aplicado IS NOT NULL)
            ORDER BY id DESC
            LIMIT 1
            """
        )
        linha = await cursor.fetchone()
        if linha is None:
            return None

        cursor = await db.execute(
            """
            SELECT key, pv_aplicado FROM leituras_ocr_campos
            WHERE leitura_id = ? AND pv_aplicado IS NOT NULL
            """,
            (linha["id"],),
        )
        valores = {campo["key"]: campo["pv_aplicado"] for campo in await cursor.fetchall()}

    return LeituraAnterior(valores=valores, minutos=max(0.0, float(linha["minutos"])))


async def purgar_imagens_antigas() -> int:
    """Apaga as fotos além da retenção e devolve quantas saíram.

    Roda no boot, e não num agendador: o volume cresce na velocidade das fotos tiradas, que
    é lenta, e um processo a mais para manter não se paga aqui.
    """
    if RETENCAO_DIAS <= 0:
        return 0

    limite = time.time() - RETENCAO_DIAS * 86400
    removidas = 0

    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, imagem_arquivo FROM leituras_ocr
            WHERE imagem_arquivo IS NOT NULL
              AND criado_em < datetime('now', ?)
            """,
            (f"-{RETENCAO_DIAS} days",),
        )
        antigas = await cursor.fetchall()

        for linha in antigas:
            caminho = os.path.join(MEDIA_DIR, linha["imagem_arquivo"])
            try:
                os.remove(caminho)
            except FileNotFoundError:
                pass
            except OSError:
                # Some do índice mesmo assim seria pior: a linha continuaria apontando para
                # um arquivo que ainda existe. Deixa para a próxima tentativa.
                continue
            await db.execute(
                "UPDATE leituras_ocr SET imagem_arquivo = NULL WHERE id = ?", (linha["id"],)
            )
            removidas += 1

        await db.commit()

    # Órfãos: arquivo em disco sem linha correspondente, resultado de queda entre o INSERT
    # e o UPDATE do nome.
    if os.path.isdir(MEDIA_DIR):
        for nome in os.listdir(MEDIA_DIR):
            caminho = os.path.join(MEDIA_DIR, nome)
            try:
                if os.path.isfile(caminho) and os.path.getmtime(caminho) < limite:
                    os.remove(caminho)
                    removidas += 1
            except OSError:
                continue

    return removidas
