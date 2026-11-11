# --- Build: Abhängigkeiten inkl. mysqlclient kompilieren ---
FROM python:3.13-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-prod.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-prod.txt

# --- Laufzeit (ohne Build-Werkzeuge) ---
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libmariadb3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

WORKDIR /app
COPY --chown=app:app . .
# CSS ist eingecheckt (assets/css/tailwind.css); hier nur statische Dateien sammeln (WhiteNoise-Manifest)
RUN DEBUG=False SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && mkdir -p media && chown app:app media

USER app
EXPOSE 8000
# Host-Header muss erlaubt sein (HOSTNAME aus der .env); X-Forwarded-Proto verhindert die HTTPS-Weiterleitung
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8000/healthz/', headers={'Host': os.environ.get('HOSTNAME', 'localhost'), 'X-Forwarded-Proto': 'https'}), timeout=4)"
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "la_tool.wsgi"]
