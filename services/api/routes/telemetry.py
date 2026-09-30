"""Receptor de eventos de telemetría del backoffice (stub de verificación).

TEMPORAL: valida el Event Envelope de cada evento del lote, registra cuántos
llegan y de qué tipo, y responde `{"received": N}`. No persiste nada. La
ingesta definitiva sustituirá el cuerpo de `ingest_events` (allowlist por
evento con `event-schemas.json`, `userId` tomado del token y persistencia)
con la misma ruta y el mismo contrato, así que el backoffice no cambia.

El cuerpo se lee como bytes y se valida como JSON sea cual sea su
`Content-Type`: `navigator.sendBeacon` envía `text/plain` para no necesitar
preflight CORS cuando la URL de la ingesta es de otro origen.
"""

import logging
from collections import Counter
from typing import Any

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from services.api.telemetry_models import TelemetryBatch, TelemetryIngestResponse


logger = logging.getLogger("trackflow.telemetry")

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


def _batch_schema() -> dict[str, Any]:
    """Esquema del lote para `/docs`, con `TelemetryEvent` incrustado.

    `openapi_extra` se copia tal cual: una referencia `#/$defs/...` no se
    resolvería dentro del documento OpenAPI.
    """
    schema = TelemetryBatch.model_json_schema(by_alias=True)
    definitions = schema.pop("$defs", {})
    items = schema["properties"]["events"]["items"]
    reference = items.pop("$ref", "")
    items.update(definitions.get(reference.rsplit("/", 1)[-1], {}))
    return schema


@router.post(
    "/events",
    response_model=TelemetryIngestResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": _batch_schema()},
                "text/plain": {"schema": {"type": "string", "description": "El mismo JSON (sendBeacon)."}},
            },
        }
    },
)
async def ingest_events(request: Request) -> TelemetryIngestResponse:
    try:
        batch = TelemetryBatch.model_validate_json(await request.body())
    except ValidationError as error:
        # Mismo 422 saneado que el resto de la API (sin `input`: podría llevar datos).
        logger.warning("Lote de telemetría rechazado: %s errores de formato.", error.error_count())
        raise RequestValidationError(
            [{**item, "loc": ("body", *item["loc"])} for item in error.errors()]
        ) from error

    event_types = [event.event_type for event in batch.events]
    sources = Counter(event.source for event in batch.events)
    logger.info(
        "Lote de telemetría recibido: %s eventos (%s) [%s]",
        len(event_types),
        ", ".join(f"{source}={count}" for source, count in sorted(sources.items())),
        ", ".join(event_types),
    )
    return TelemetryIngestResponse(received=len(batch.events))
