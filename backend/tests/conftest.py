"""Isola a suíte do ambiente real.

Precisa rodar antes de qualquer import de `backend.database`: o caminho do banco é lido
uma vez, na importação do módulo. O conftest é carregado antes dos módulos de teste, que é
o que torna isto possível.
"""

from __future__ import annotations

import os
import tempfile

_TEMP = tempfile.mkdtemp(prefix="carta-testes-")

os.environ["CARTA_DB_PATH"] = os.path.join(_TEMP, "teste.db")
os.environ["CARTA_MEDIA_DIR"] = os.path.join(_TEMP, "media")
# Teste não precisa acumular JPEG em disco.
os.environ["CARTA_GUARDAR_IMAGENS"] = "0"
