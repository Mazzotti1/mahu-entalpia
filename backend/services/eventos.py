from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

# Quantos avisos uma conexão lenta pode acumular antes de começar a perder. Perder não é
# grave: o cliente recebe o id do próximo evento e o `Last-Event-ID` da reconexão cobre
# qualquer buraco. O que não pode é uma conexão travada segurar memória sem limite.
TAMANHO_FILA = 64


class DifusorSimulacoes:
    """Avisa as conexões SSE abertas quando uma simulação nova é gravada.

    Vive na memória do processo, o que basta enquanto o uvicorn roda com um worker só.
    Com `--workers 2` cada worker só enxergaria as próprias escritas, e aí o caminho é
    trocar isto por um pub/sub externo (Redis) — a interface pública é a mesma.
    """

    def __init__(self) -> None:
        self._inscritos: set[asyncio.Queue[int]] = set()

    @property
    def inscritos(self) -> int:
        return len(self._inscritos)

    def publicar(self, simulacao_id: int) -> None:
        for fila in list(self._inscritos):
            try:
                fila.put_nowait(simulacao_id)
            except asyncio.QueueFull:
                # Conexão que não consome: segue o baile, a reconexão dela se acerta.
                continue

    @asynccontextmanager
    async def inscrever(self) -> AsyncIterator[asyncio.Queue[int]]:
        fila: asyncio.Queue[int] = asyncio.Queue(maxsize=TAMANHO_FILA)
        self._inscritos.add(fila)
        try:
            yield fila
        finally:
            self._inscritos.discard(fila)


difusor = DifusorSimulacoes()
