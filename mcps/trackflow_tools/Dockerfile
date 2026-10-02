# Contenedor del servidor MCP (`mcps/trackflow_tools`) para desarrollo. Se construye desde la raíz del monorepo
# (docker-compose.yml) porque el servidor importa `services.api` y `packages.shared`. El código llega por bind mount;
# la imagen aporta Python y las dependencias.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY services/api/requirements.txt api-requirements.txt
COPY mcps/trackflow_tools/requirements.txt mcp-requirements.txt
RUN uv pip install --system --no-cache -r api-requirements.txt -r mcp-requirements.txt

EXPOSE 8001

CMD ["python", "-m", "mcps.trackflow_tools"]
