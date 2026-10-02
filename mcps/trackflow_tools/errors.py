"""Códigos de error de las tools y códigos de salida del proceso (tabla completa en el README).

Una tool que falla devuelve `isError: true` con un único bloque de texto JSON
`{"code", "message", "errors"?}`: el código es estable y distinto para cada causa, así que el cliente puede actuar
sin interpretar el mensaje. Los fallos de autenticación no llegan aquí: los responde MCP Auth con HTTP 401 antes
de que la petición alcance el servidor MCP.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from mcp.types import TextContent

from fastmcp.tools import ToolResult


class ErrorCode(str, Enum):
    # Autorización: el token es válido, pero no le da permiso para esto.
    INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"
    INVENTORY_READ_ONLY = "INVENTORY_READ_ONLY"
    # Validación: argumentos que no cumplen el esquema o una regla de negocio de la API (transición no permitida).
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    # La API de TrackFlow no respondió, tardó demasiado o falló.
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"


# Códigos de salida del proceso (`python -m mcps.trackflow_tools`).
EXIT_CONFIG_ERROR = 2
EXIT_AUTH_SERVER_UNREACHABLE = 3


class ToolFailure(Exception):
    """Fallo controlado de una tool; el middleware lo convierte en un resultado `isError`."""

    def __init__(self, code: ErrorCode, message: str, errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.errors = errors or []

    def to_result(self) -> ToolResult:
        body: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.errors:
            body["errors"] = self.errors
        return ToolResult(content=[TextContent(type="text", text=json.dumps(body, ensure_ascii=False))], is_error=True)
