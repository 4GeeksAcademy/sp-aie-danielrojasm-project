"""Utilidades compartidas por los módulos de prueba."""

import asyncio
import json
from typing import Any


TEST_SECRET = "test-secret-key-with-at-least-32-characters"
DEFAULT_PASSWORD = "correct-password"


class FakeRequest:
    """Sustituto mínimo de `starlette.Request` para `_login_payload`.

    Solo implementa lo que la lógica de login lee (cabeceras, cliente,
    `json()` y `form()`), sin pasar por el servidor HTTP.
    """

    client = None  # sin conexión real: la telemetría usa `ip_prefix = unknown`

    def __init__(
        self,
        body: Any = None,
        *,
        form: dict[str, str] | None = None,
        raw_json: str | None = None,
    ) -> None:
        self._body = body
        self._form = form
        self._raw_json = raw_json
        content_type = (
            "application/x-www-form-urlencoded" if form is not None else "application/json"
        )
        self.headers = {"content-type": content_type}

    async def json(self) -> Any:
        if self._raw_json is not None:
            return json.loads(self._raw_json)
        return self._body

    async def form(self) -> dict[str, str]:
        return self._form or {}


def run(coroutine: Any) -> Any:
    """Ejecuta un handler asíncrono de FastAPI como una función normal."""
    return asyncio.run(coroutine)
