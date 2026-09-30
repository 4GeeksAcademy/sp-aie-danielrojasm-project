# Contenedor de la API FastAPI para desarrollo, con recarga en caliente.
# El código (services/ y packages/) llega por bind mount desde
# docker-compose.yml; la imagen aporta Python y las dependencias.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

# La API se importa como `services.api.main` desde la raíz del monorepo.
WORKDIR /app

COPY api/requirements.txt requirements.txt
RUN uv pip install --system --no-cache -r requirements.txt

COPY . ./services

EXPOSE 8000

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "services", "--reload-dir", "packages"]
