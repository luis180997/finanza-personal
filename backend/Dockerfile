# =============================================================================
#  Backend: FastAPI + uvicorn
# =============================================================================
#  Una sola etapa: no hay nada que compilar. La imagen final pesa ~450 MB, casi
#  todo del cliente de Google y de lxml.
#
#  IMPORTANTE: un solo worker, a proposito.
#    - SQLite no admite varios procesos escribiendo comodamente.
#    - El programador de sincronizacion (APScheduler) vive dentro del proceso:
#      con N workers, la sincronizacion con Gmail correria N veces en paralelo.
#  Para un uso personal, un worker sobra: la carga es de unas pocas peticiones
#  por minuto.
# =============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Las dependencias primero: esta capa se cachea y no se reconstruye al cambiar codigo.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY pyproject.toml alembic.ini ./

# Usuario sin privilegios. /app/data se crea aqui con su propietario correcto:
# Docker copia esos permisos al inicializar el volumen con nombre.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data /app/secrets \
    && chown -R app:app /app

USER app

ENV DATA_DIR=/app/data \
    SECRETS_DIR=/app/secrets

EXPOSE 8000

# Sin curl en la imagen: el chequeo lo hace el propio Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/salud', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
