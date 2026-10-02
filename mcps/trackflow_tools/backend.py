"""Cliente HTTP de la API de TrackFlow (`TRACKFLOW_API_URL`): el servidor MCP se apoya en ella, no la reemplaza.

- **Auth hacia la API:** la API valida sus propios JWT HS256, no los de Keycloak. El servidor firma un token de vida
  corta para la cuenta de servicio `MCP_SERVICE_USER_ID` con `JWT_SECRET_KEY`, como hacía la tool directa del agente.
- **Inventario de solo lectura por diseño:** `InventoryReader` solo sabe hacer `GET` bajo `/inventory`; no existe en
  el servidor ningún método que escriba en el inventario.
- **Errores:** 404 → `NOT_FOUND`; 400 de la API → `VALIDATION_ERROR` con sus `errors[{field, message}]`; red caída,
  timeout, 401/403 o 5xx → `UPSTREAM_UNAVAILABLE`. El detalle técnico va al log `trackflow.mcp`.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any

import httpx

from mcps.trackflow_tools.errors import ErrorCode, ToolFailure
from services.api.security import create_access_token


logger = logging.getLogger("trackflow.mcp")

DEFAULT_API_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 5.0
SERVICE_TOKEN_TTL = timedelta(minutes=5)
INCIDENTS_PATH = "/api/incidents"
INVENTORY_PATH = "/inventory"


def api_url() -> str:
    return (os.getenv("TRACKFLOW_API_URL") or DEFAULT_API_URL).rstrip("/")


async def request(method: str, path: str, *, json: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> Any:
    service_user = os.getenv("MCP_SERVICE_USER_ID")
    if not service_user:
        logger.error("MCP_SERVICE_USER_ID no está configurada: el servidor no puede autenticarse en la API.")
        raise ToolFailure(ErrorCode.UPSTREAM_UNAVAILABLE, "El servidor MCP no tiene credenciales para la API de TrackFlow.")
    headers = {"Authorization": f"Bearer {create_access_token(service_user, SERVICE_TOKEN_TTL)}"}
    try:
        async with http_client() as client:
            response = await client.request(method, path, json=json, params=params, headers=headers)
    except httpx.TimeoutException as error:
        logger.error("API %s %s timeout tras %.0f s", method, path, TIMEOUT_SECONDS)
        raise ToolFailure(ErrorCode.UPSTREAM_UNAVAILABLE, "La API de TrackFlow no respondió a tiempo; reintenta en unos minutos.") from error
    except httpx.HTTPError as error:
        logger.error("API %s %s no disponible: %s", method, path, type(error).__name__)
        raise ToolFailure(ErrorCode.UPSTREAM_UNAVAILABLE, "La API de TrackFlow no está disponible; reintenta en unos minutos.") from error

    if response.status_code < 300:
        return response.json()
    body = _json_or_empty(response)
    if response.status_code == 404:
        raise ToolFailure(ErrorCode.NOT_FOUND, str(body.get("detail") or "El recurso no existe."))
    if response.status_code == 400:
        errors = [{"field": str(item.get("field")), "message": str(item.get("message"))} for item in body.get("errors", [])]
        raise ToolFailure(ErrorCode.VALIDATION_ERROR, str(body.get("detail") or "Datos no válidos."), errors)
    logger.error("API %s %s respondió %d", method, path, response.status_code)
    raise ToolFailure(ErrorCode.UPSTREAM_UNAVAILABLE, "La API de TrackFlow respondió con un error; reintenta en unos minutos.")


def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=api_url(), timeout=TIMEOUT_SECONDS)


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class InventoryReader:
    """Única vía del servidor hacia el inventario: solo `GET` y solo bajo `/inventory`."""

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await request("GET", f"{INVENTORY_PATH}{path}", params=params)
