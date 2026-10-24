"""Notificaciones en tiempo real de `/rfps/events`: el worker publica y la API las reenvía por SSE.

El análisis corre en el worker de Celery y el stream lo sirve la API, así que el evento cruza procesos por Redis
(el mismo de la cola de tareas, `REDIS_URL`). Se usa un stream y no pub/sub porque guarda los últimos
`STREAM_MAXLEN` eventos con un id ordenado: ese id es el `id:` de SSE y, al reconectar, el cliente lo devuelve en
`Last-Event-ID` para recibir lo que se perdió mientras estaba desconectado (replay corto en servidor).

- `notify_rfp_ticket_created` (worker): construye `RfpTicketCreatedEvent` y lo añade al stream. Si Redis no
  responde, lo registra y sigue: el análisis no depende de la notificación.
- `RfpEventBus.read_after` (API): espera hasta `block_ms` a eventos posteriores a un id; cada conexión SSE lee
  por su cuenta.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import redis
import redis.asyncio as redis_async
from redis.exceptions import RedisError

from data.pipelines.rfp_intake.schema import RfpTicket
from services.rfp_intake.models import RfpTicketCreatedEvent


logger = logging.getLogger("trackflow.rfp_intake.events")

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
STREAM_KEY = "trackflow:rfp_events"
# Unas cuantas semanas de RFPs: de sobra para cualquier desconexión razonable.
STREAM_MAXLEN = 1000
RFP_TICKET_CREATED = "rfp_ticket_created"
# Primer id posible de un stream de Redis: "desde el principio".
STREAM_START = "0-0"
_STREAM_ID = re.compile(r"^\d+-\d+$")


class EventsUnavailableError(RuntimeError):
    """Redis no respondió: no se pueden leer las notificaciones."""


@dataclass(frozen=True)
class StreamEvent:
    id: str
    event: str
    data: str


def is_stream_id(value: str) -> bool:
    return bool(_STREAM_ID.match(value))


class RfpEventBus:
    def __init__(self, client: redis.Redis, async_client: redis_async.Redis, stream_key: str = STREAM_KEY):
        self.client = client
        self.async_client = async_client
        self.stream_key = stream_key

    def publish(self, event: str, payload: str) -> str:
        return self.client.xadd(
            self.stream_key, {"event": event, "data": payload}, maxlen=STREAM_MAXLEN, approximate=True
        )

    async def latest_id(self) -> str:
        """Id del último evento: un cliente nuevo solo recibe lo que llegue a partir de ahora."""
        try:
            entries = await self.async_client.xrevrange(self.stream_key, count=1)
        except RedisError as error:
            raise EventsUnavailableError(type(error).__name__) from error
        return _decode(entries[0][0]) if entries else STREAM_START

    async def read_after(self, last_id: str, block_ms: int) -> list[StreamEvent]:
        try:
            response = await self.async_client.xread({self.stream_key: last_id}, block=block_ms, count=50)
        except RedisError as error:
            raise EventsUnavailableError(type(error).__name__) from error
        return [_stream_event(entry_id, fields) for _, entries in response or [] for entry_id, fields in entries]


def _decode(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _stream_event(entry_id: Any, fields: dict[Any, Any]) -> StreamEvent:
    decoded = {_decode(key): _decode(value) for key, value in fields.items()}
    return StreamEvent(id=_decode(entry_id), event=decoded["event"], data=decoded["data"])


_bus: RfpEventBus | None = None


def get_event_bus() -> RfpEventBus:
    """El bus del proceso sobre `REDIS_URL` (las conexiones se abren con la primera operación)."""
    global _bus
    if _bus is None:
        url = os.getenv("REDIS_URL", "").strip() or DEFAULT_REDIS_URL
        _bus = RfpEventBus(
            redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=3),
            # Sin socket_timeout: el XREAD bloqueante espera más que cualquier timeout corto.
            redis_async.Redis.from_url(url, socket_connect_timeout=2),
        )
    return _bus


def use_event_bus(bus: RfpEventBus | None) -> None:
    """Sustituye el bus del proceso (tests con un Redis en memoria)."""
    global _bus
    _bus = bus


def notify_rfp_ticket_created(ticket: RfpTicket, metadata: dict[str, Any]) -> None:
    """Callback de `runner.process_ticket`: la RFP es válida y el ticket entra en proceso."""
    event = RfpTicketCreatedEvent(
        ticket_id=ticket.ticket_id,
        rfp_id=ticket.rfp_id or "",
        client_name=metadata.get("client_name"),
        client_country=metadata.get("client_country"),
        services_requested=metadata.get("services_requested") or [],
        status=ticket.status,
        original_filename=ticket.original_filename,
        created_at=ticket.created_at,
    )
    try:
        entry_id = get_event_bus().publish(RFP_TICKET_CREATED, event.model_dump_json())
    except RedisError as error:
        # Sin aviso en vivo, la RFP sigue apareciendo en `GET /rfps` (la UI lo vuelve a pedir al reconectar).
        logger.error(
            "ticket=%s rfp_id=%s evento %s no publicado: %s",
            event.ticket_id,
            event.rfp_id,
            RFP_TICKET_CREATED,
            type(error).__name__,
        )
        return
    logger.info("ticket=%s rfp_id=%s evento %s id=%s", event.ticket_id, event.rfp_id, RFP_TICKET_CREATED, entry_id)
