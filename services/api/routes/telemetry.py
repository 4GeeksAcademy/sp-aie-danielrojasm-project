"""Ingesta de eventos de telemetría del backoffice: `POST /telemetry/events`.

Misma ruta y mismo sobre que el stub al que sustituye (`{"events": [...]}`),
así que el backoffice no cambia. Cada evento se valida por separado y el lote
nunca se cancela por uno malo:

1. `TelemetryEvent.model_validate` (el contrato del envelope, sin cambios).
2. `event_type` del catálogo de `event-schemas.json` y emitido por el
   navegador: los eventos de la API (los obligatorios incluidos) solo los
   escribe la API, nunca llegan por aquí.
3. `timestamp` como mucho 5 minutos en el futuro (riesgo R7 del plan).
4. `properties` recortado al allowlist del evento (se descartan las claves
   desconocidas y se registran sus nombres, nunca sus valores).

Los válidos se guardan con un único bulk insert en `telemetry_events` y la
respuesta es `{"received", "stored", "rejected"}`. Solo el sobre puede
devolver 422 (JSON ilegible, sin arreglo `events` o más de 100 eventos); si el
almacén no responde, 503 para que el backoffice reintente (el `eventId` es la
clave primaria, así que el reintento no duplica filas).

El cuerpo se lee como bytes y se valida como JSON sea cual sea su
`Content-Type`: `navigator.sendBeacon` envía `text/plain` para no necesitar
preflight CORS cuando la URL de la ingesta es de otro origen.
"""

import logging
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from services.api import telemetry
from services.api.database import DatabaseNotConfiguredError, get_engine
from services.api.telemetry_models import (
    TelemetryBatch,
    TelemetryEvent,
    TelemetryIngestEnvelope,
    TelemetryIngestResponse,
)
from services.api.telemetry_storage import TABLE_NAME, store_events


logger = logging.getLogger("trackflow.telemetry")

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# Emisores que pueden usar esta ingesta. La API persiste los suyos directamente.
INGEST_SOURCES = frozenset({"backoffice"})
MAX_CLOCK_SKEW = timedelta(minutes=5)
TELEMETRY_UNAVAILABLE_DETAIL = (
    "El almacén de telemetría no está disponible ahora mismo; el lote se puede reintentar."
)


def get_telemetry_db() -> Iterator[Session]:
    """Sesión del almacén; sin `DATABASE_URL` la ingesta responde 503 con su propio mensaje."""
    try:
        engine = get_engine()
    except DatabaseNotConfiguredError as error:
        logger.error("Ingesta de telemetría sin almacén: %s", error)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, TELEMETRY_UNAVAILABLE_DETAIL) from error
    with Session(engine) as session:
        yield session


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


def _parse_envelope(body: bytes) -> TelemetryIngestEnvelope:
    try:
        return TelemetryIngestEnvelope.model_validate_json(body)
    except ValidationError as error:
        # Mismo 422 saneado que el resto de la API (sin `input`: podría llevar datos).
        logger.warning("Lote de telemetría rechazado: %s errores en el sobre.", error.error_count())
        raise RequestValidationError(
            [{**item, "loc": ("body", *item["loc"])} for item in error.errors()]
        ) from error


def _accept(raw: Any, now: datetime) -> tuple[TelemetryEvent | None, str]:
    """Valida un evento crudo. Devuelve el evento listo para guardar o el motivo del rechazo."""
    try:
        parsed = TelemetryEvent.model_validate(raw)
    except ValidationError:
        return None, "envelope"
    sources = telemetry.event_sources(parsed.event_type)
    if sources is None:
        return None, "unknown_event_type"
    if parsed.source not in INGEST_SOURCES or parsed.source not in sources:
        return None, "source"
    if datetime.fromisoformat(parsed.timestamp) > now + MAX_CLOCK_SKEW:
        return None, "future_timestamp"

    allowed = telemetry.allowlist(parsed.event_type)
    dropped = sorted(set(parsed.properties) - allowed)
    if dropped:
        logger.warning(
            "Evento %s: claves fuera del allowlist descartadas: %s", parsed.event_type, ", ".join(dropped)
        )
        parsed = parsed.model_copy(
            update={"properties": {key: value for key, value in parsed.properties.items() if key in allowed}}
        )
    return parsed, ""


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
async def ingest_events(
    request: Request, session: Session = Depends(get_telemetry_db)
) -> TelemetryIngestResponse:
    envelope = _parse_envelope(await request.body())

    now = datetime.now(timezone.utc)
    accepted: list[TelemetryEvent] = []
    rejections: Counter[str] = Counter()
    for raw in envelope.events:
        parsed, reason = _accept(raw, now)
        if parsed is None:
            rejections[reason] += 1
        else:
            accepted.append(parsed)

    try:
        # Una sola sentencia por lote, fuera del bucle de eventos de asyncio.
        inserted = await run_in_threadpool(store_events, session, accepted)
    except SQLAlchemyError as error:
        # La traza (con host y usuario de la conexión) solo va al log.
        logger.exception("No se pudo guardar un lote de %s eventos en %s.", len(accepted), TABLE_NAME)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, TELEMETRY_UNAVAILABLE_DETAIL) from error

    received, rejected = len(envelope.events), sum(rejections.values())
    logger.info(
        "Lote de telemetría: %s recibidos, %s guardados (%s ya existían), %s rechazados%s [%s]",
        received,
        len(accepted),
        len(accepted) - inserted,
        rejected,
        f" ({', '.join(f'{reason}={count}' for reason, count in sorted(rejections.items()))})"
        if rejected
        else "",
        ", ".join(event.event_type for event in accepted),
    )
    return TelemetryIngestResponse(received=received, stored=len(accepted), rejected=rejected)
