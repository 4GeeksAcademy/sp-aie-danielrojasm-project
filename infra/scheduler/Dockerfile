# Contenedor `scheduler`: dispara los jobs nocturnos con cron, fuera de la API.
# Supercronic es un cron pensado para contenedores: hereda el entorno de
# `env_file`, escribe en la salida del contenedor y no solapa ejecuciones del
# mismo job. El código (services/, data/ y scripts/) y el crontab llegan por
# bind mount desde docker-compose.yml; la imagen aporta Python, dependencias y cron.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC

# Binario linux-amd64 verificado por SHA1 (valor publicado con la release).
ARG SUPERCRONIC_VERSION=v0.2.49
ARG SUPERCRONIC_SHA1SUM=e63c11a9726b775a6a11801e81af4f3fb926aa68
ADD https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64 /usr/local/bin/supercronic
RUN echo "${SUPERCRONIC_SHA1SUM}  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod +x /usr/local/bin/supercronic

RUN pip install --no-cache-dir uv

WORKDIR /app

# Mismas dependencias que la API: el pipeline necesita Prefect, Pandas y psycopg2.
COPY api/requirements.txt requirements.txt
RUN uv pip install --system --no-cache -r requirements.txt

CMD ["supercronic", "-passthrough-logs", "/app/infra/scheduler/crontab"]
