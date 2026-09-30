"""Emisor de telemetría de la API (`docs/telemetry/telemetry-plan.md`, sección 7).

`emit(event_type, properties)` construye el Event Envelope con el contexto de la
petición en curso (`requestId`, `sessionId`), descarta las claves de
`properties` que no están en el allowlist del evento y entrega el evento a los
sumideros de `SINKS`. Hoy el único sumidero es el log `trackflow.telemetry`
(una línea JSON por evento); la persistencia añadirá el suyo sin tocar a los
emisores.

La telemetría nunca cambia la respuesta al usuario: cualquier fallo al emitir
se registra como WARNING (sin valores, solo nombres) y se descarta.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from services.api.telemetry_models import EventEnvironment, TelemetryEvent


logger = logging.getLogger("trackflow.telemetry")

DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "telemetry" / "event-schemas.json"
)
ENVIRONMENTS: tuple[EventEnvironment, ...] = ("development", "staging", "production")
UNKNOWN_SESSION = "unknown"
ANONYMOUS_USER = "anonymous"

_request_id: ContextVar[str | None] = ContextVar("telemetry_request_id", default=None)
_session_id: ContextVar[str] = ContextVar("telemetry_session_id", default=UNKNOWN_SESSION)


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

def telemetry_endpoint() -> str | None:
    """URL de la ingesta de eventos (`TELEMETRY_ENDPOINT`).

    Hoy apunta al receptor `POST /telemetry/events` de esta misma API. Cuando la
    ingesta persista los eventos, el publicador de la API entregará aquí los
    suyos y el backoffice seguirá usando su propia variable, sin cambios.
    """
    endpoint = os.getenv("TELEMETRY_ENDPOINT", "").strip()
    return endpoint or None


def telemetry_environment() -> EventEnvironment:
    value = os.getenv("TELEMETRY_ENVIRONMENT", "development").strip()
    for environment in ENVIRONMENTS:
        if value == environment:
            return environment
    logger.warning("TELEMETRY_ENVIRONMENT no válido; se usa 'development'.")
    return "development"


def _schema_path() -> Path:
    return Path(os.getenv("TELEMETRY_SCHEMA_PATH", str(DEFAULT_SCHEMA_PATH)))


@lru_cache(maxsize=1)
def _event_catalog() -> dict[str, tuple[str, frozenset[str], frozenset[str]]]:
    """`event_type` → (schemaVersion, allowlist de `properties`, emisores) desde el JSON Schema."""
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    catalog: dict[str, tuple[str, frozenset[str], frozenset[str]]] = {}
    for event_type in schema["x-eventTypes"]:
        event_schema = schema["definitions"][event_type]["allOf"][1]["properties"]
        catalog[event_type] = (
            event_schema["schemaVersion"]["const"],
            frozenset(event_schema["properties"]["properties"]),
            frozenset(event_schema["source"]["enum"]),
        )
    return catalog


def allowlist(event_type: str) -> frozenset[str]:
    return _event_catalog()[event_type][1]


# ---------------------------------------------------------------------------
# Contexto de la petición (lo fija `timing_middleware`)
# ---------------------------------------------------------------------------

def _is_uuid_v4(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def accept_request_id(header: str | None) -> str:
    """El `X-Request-Id` del backoffice si es un UUID v4; si no, uno nuevo."""
    return header if header is not None and _is_uuid_v4(header) else str(uuid4())


def accept_session_id(header: str | None) -> str:
    return header if header is not None and _is_uuid_v4(header) else UNKNOWN_SESSION


def bind_request(request_id: str, session_id: str) -> None:
    """Asocia los identificadores de correlación a la petición en curso.

    No se restauran al terminar: cada petición los fija al empezar, y así los
    handlers de error externos al middleware (500) siguen viéndolos.
    """
    _request_id.set(request_id)
    _session_id.set(session_id)


def current_request_id() -> str | None:
    return _request_id.get()


# ---------------------------------------------------------------------------
# Emisión
# ---------------------------------------------------------------------------

def _log_sink(event: TelemetryEvent) -> None:
    logger.info("%s", event.model_dump_json())


# Destinos de los eventos emitidos. Los tests añaden uno que los recoge.
SINKS: list[Callable[[TelemetryEvent], None]] = [_log_sink]


def _utc_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def emit(
    event_type: str,
    properties: Mapping[str, Any],
    *,
    user_id: str | None = None,
) -> TelemetryEvent | None:
    """Emite un evento de la API. Devuelve el evento o `None` si no se pudo emitir."""
    try:
        schema_version, allowed, sources = _event_catalog()[event_type]
    except (OSError, KeyError, ValueError) as error:
        logger.warning(
            "Evento %s no emitido: esquema no disponible (%s).", event_type, type(error).__name__
        )
        return None
    if "api" not in sources:
        # Un evento del navegador emitido desde la API duplicaría (o suplantaría) el suyo.
        logger.warning("Evento %s no emitido: su emisor no es la API.", event_type)
        return None

    dropped = sorted(set(properties) - allowed)
    if dropped:
        # Solo el nombre de la clave, nunca su valor.
        logger.warning(
            "Evento %s: claves fuera del allowlist descartadas: %s", event_type, ", ".join(dropped)
        )
    try:
        event = TelemetryEvent(
            eventId=str(uuid4()),
            timestamp=_utc_timestamp(),
            sessionId=_session_id.get(),
            userId=user_id or ANONYMOUS_USER,
            event_type=event_type,
            schemaVersion=schema_version,
            requestId=_request_id.get() or str(uuid4()),
            source="api",
            environment=telemetry_environment(),
            properties={key: value for key, value in properties.items() if key in allowed},
        )
    except ValidationError as error:
        fields = ", ".join(sorted({str(item["loc"][0]) for item in error.errors()}))
        logger.warning("Evento %s no emitido: envelope no válido en %s.", event_type, fields)
        return None

    for sink in SINKS:
        try:
            sink(event)
        except Exception:  # noqa: BLE001 - un sumidero caído no afecta a la petición
            logger.warning("Un sumidero de telemetría falló con %s.", event_type)
    return event


# ---------------------------------------------------------------------------
# Seudonimización (sección 10 del plan)
# ---------------------------------------------------------------------------

_warned_missing_hash_key = False


def email_hash(email: str) -> str | None:
    """HMAC-SHA256 del email normalizado, truncado a 16 hex. `None` sin clave."""
    global _warned_missing_hash_key
    key = os.getenv("TELEMETRY_HASH_KEY", "")
    if not key:
        if not _warned_missing_hash_key:
            logger.warning("Falta TELEMETRY_HASH_KEY: los eventos llevarán email_hash nulo.")
            _warned_missing_hash_key = True
        return None
    digest = hmac.new(key.encode(), email.strip().lower().encode(), hashlib.sha256)
    return digest.hexdigest()[:16]


def ip_prefix(host: str | None) -> str:
    """IP truncada a /24 (IPv4) o /48 (IPv6); nunca la dirección completa."""
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return "unknown"
    prefix = 24 if address.version == 4 else 48
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False).network_address)


_UA_FAMILIES = (
    ("Edge", re.compile(r"Edg(?:e|A|iOS)?/(\d+)")),
    ("Opera", re.compile(r"OPR/(\d+)")),
    ("Firefox", re.compile(r"Firefox/(\d+)")),
    ("Chrome", re.compile(r"(?:Chrome|CriOS)/(\d+)")),
    ("Safari", re.compile(r"Version/(\d+).*Safari/")),
)


def ua_family(user_agent: str | None) -> str:
    """Familia y versión mayor del navegador (`Chrome 140`); `other` si no se reconoce."""
    for family, pattern in _UA_FAMILIES:
        match = pattern.search(user_agent or "")
        if match:
            return f"{family} {match.group(1)}"
    return "other"
