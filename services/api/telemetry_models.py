"""Modelos del Event Envelope de telemetría (`docs/telemetry/telemetry-plan.md`, sección 6).

`TelemetryEvent` es el contrato común de todo evento, lo emita el backoffice,
la API o un job. Lo usan el receptor `POST /telemetry/events` y el emisor de la
API (`services/api/telemetry.py`), y se reutilizará sin cambios cuando la
ingesta persista los eventos. Los patrones son los de `definitions/envelope`
de `docs/telemetry/event-schemas.json` (un test comprueba que coinciden).

Aquí solo se valida el envelope. El allowlist de `properties` de cada
`event_type` lo aplica el emisor y, en la fase de persistencia, la ingesta.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


UUID_V4_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
_UUID_V4 = UUID_V4_PATTERN.strip("^$")
TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
SESSION_ID_PATTERN = rf"^(?:{_UUID_V4}|job:[a-z_]+:{_UUID_V4}|unknown)$"
USER_ID_PATTERN = rf"^(?:{_UUID_V4}|anonymous|system:[a-z_]+)$"
EVENT_TYPE_PATTERN = r"^[a-z]+(?:_[a-z]+)+$"
SCHEMA_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"

# Un lote del backoffice lleva como mucho 20 eventos; el margen cubre los que
# se acumulan sin red y salen juntos al cerrar la pestaña.
MAX_EVENTS_PER_BATCH = 100

EventSource = Literal["backoffice", "api", "job"]
EventEnvironment = Literal["development", "staging", "production"]


class TelemetryEvent(BaseModel):
    """Event Envelope: los diez campos de primer nivel, ni uno más."""

    model_config = ConfigDict(extra="forbid", validate_by_name=True, serialize_by_alias=True)

    event_id: str = Field(alias="eventId", pattern=UUID_V4_PATTERN)
    timestamp: str = Field(
        pattern=TIMESTAMP_PATTERN,
        description="Momento del hecho (no del envío), ISO 8601 UTC con milisegundos.",
    )
    session_id: str = Field(alias="sessionId", pattern=SESSION_ID_PATTERN)
    user_id: str = Field(
        alias="userId",
        pattern=USER_ID_PATTERN,
        description="`sub` del JWT, nunca el email; `anonymous` antes del login.",
    )
    event_type: str = Field(pattern=EVENT_TYPE_PATTERN, max_length=60)
    schema_version: str = Field(alias="schemaVersion", pattern=SCHEMA_VERSION_PATTERN)
    request_id: str = Field(alias="requestId", pattern=UUID_V4_PATTERN)
    source: EventSource
    environment: EventEnvironment
    properties: dict[str, Any]


class TelemetryBatch(BaseModel):
    """Cuerpo de `POST /telemetry/events`: los eventos siempre llegan en lote."""

    model_config = ConfigDict(extra="forbid")

    events: list[TelemetryEvent] = Field(min_length=1, max_length=MAX_EVENTS_PER_BATCH)


class TelemetryIngestResponse(BaseModel):
    received: int = Field(description="Eventos aceptados del lote.")
