# Contexto de build: a RAIZ do projeto (os imports são `backend.main`, `backend.services`...).
#   docker build -f backend/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Banco e modelos de OCR ficam fora da imagem, em volumes montados pelo compose.
    CARTA_DB_PATH=/data/simulador.db \
    EASYOCR_MODULE_PATH=/models/easyocr

# opencv-python-headless dispensa servidor gráfico, mas ainda liga contra libglib/libgomp.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# O wheel padrão do torch (dependência do easyocr) arrasta o runtime CUDA inteiro: a
# imagem sai com 8,62 GB contra 2,05 GB pelo índice CPU-only, e nada disso é usado —
# services/mahu_ocr.py instancia o easyocr com gpu=False. Para reativar as wheels com
# CUDA, passe o argumento vazio: --build-arg TORCH_INDEX_URL=
ARG TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"

COPY backend/requirements.txt backend/requirements.txt
RUN if [ -n "$TORCH_INDEX_URL" ]; then \
      pip install --no-cache-dir --index-url "$TORCH_INDEX_URL" torch torchvision; \
    fi \
 && pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/

# Criados com o dono certo ANTES de virar volume: um volume nomeado vazio herda a
# permissão do diretório da imagem, então o processo não-root consegue escrever.
RUN useradd --create-home --uid 10001 carta \
 && mkdir -p /data /models/easyocr \
 && chown -R carta:carta /data /models /app

USER carta

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
