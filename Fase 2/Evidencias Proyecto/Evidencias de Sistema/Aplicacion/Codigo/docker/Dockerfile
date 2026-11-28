# VEXA Local — imagen del backend (Flask + Waitress) con el frontend incluido.
#
# Se usa junto con docker-compose.yml: este contenedor comparte la red del contenedor de Tailscale,
# así que VEXA sigue escuchando solo en 127.0.0.1 y en la IP 100.x de Tailscale (nunca 0.0.0.0,
# sin puertos publicados en el equipo). Detalle y advertencias: docs/docker.md
# El contexto de construcción es Codigo/ (lo fija docker-compose.yml); las rutas COPY parten de ahí.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OCR de PDF escaneados (opcional en VEXA, pero se incluye con el idioma español).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/run.py backend/run.py
COPY backend/vexa backend/vexa
COPY backend/scripts backend/scripts
COPY frontend frontend

# Usuario sin privilegios. /data/vexa guarda la base, los documentos cifrados y vault.key (subcarpeta del
# volumen: así restaurar con --replace puede renombrarla, cosa imposible con el punto de montaje /data).
# /respaldos guarda los respaldos automáticos (VEXA exige que estén fuera de la carpeta de datos).
RUN useradd --create-home --uid 10001 vexa \
    && mkdir -p /data /respaldos \
    && chown vexa:vexa /data /respaldos
USER vexa

ENV VEXA_DATA_DIR=/data/vexa \
    VEXA_BACKUP_DIR=/respaldos \
    VEXA_ENV=production \
    VEXA_SERVER=waitress \
    VEXA_HOST=127.0.0.1 \
    VEXA_PORT=5000 \
    VEXA_TESSERACT_CMD=/usr/bin/tesseract

VOLUME ["/data", "/respaldos"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('VEXA_PORT','5000'), timeout=4)" || exit 1

CMD ["python", "backend/run.py"]
