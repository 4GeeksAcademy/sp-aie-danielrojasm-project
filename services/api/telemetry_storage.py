"""Almacén de eventos de telemetría: tabla `telemetry_events` en Supabase.

Una fila por evento, escrita una sola vez. Las columnas fijas (`event_type`,
`timestamp`, `service`) sostienen las consultas analíticas; `tags` (JSONB)
guarda las `properties` del envelope ya filtradas por el allowlist del evento.

- `id` es el `eventId` del envelope: un lote reintentado tras un 5xx no
  duplica filas (`ON CONFLICT DO NOTHING`).
- Cada lote se inserta con un único `INSERT ... VALUES (...), (...)` en una
  sola transacción, nunca un INSERT por evento.
- En PostgreSQL un trigger rechaza cualquier UPDATE o DELETE: los eventos son
  hechos inmutables. La tabla tiene RLS activado y sin políticas, así que la
  API REST pública de Supabase no la lee ni la escribe; solo la API, que se
  conecta como propietaria con `DATABASE_URL`.

`ApiEventBuffer` es el sumidero de los eventos que emite la propia API
(`telemetry.emit`): los acumula y `timing_middleware` los persiste en bloque al
terminar cada respuesta.
"""

import logging
import threading
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import DDL, Column, DateTime, Index, String, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.types import JSON
from sqlmodel import Field, Session, SQLModel

from services.api.database import DatabaseNotConfiguredError, get_engine
from services.api.telemetry_models import TelemetryEvent


logger = logging.getLogger("trackflow.telemetry")

TABLE_NAME = "telemetry_events"


class TelemetryEventRecord(SQLModel, table=True):
    __tablename__ = TABLE_NAME
    __table_args__ = (
        Index("ix_telemetry_events_timestamp", "timestamp"),
        Index("ix_telemetry_events_event_type", "event_type"),
        Index("ix_telemetry_events_tags", "tags", postgresql_using="gin"),
    )

    id: str = Field(primary_key=True, max_length=36, description="`eventId` del envelope.")
    event_type: str = Field(max_length=60)
    timestamp: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    service: str = Field(max_length=20, description="`source` del envelope: backoffice, api o job.")
    user_id: str = Field(max_length=64)
    session_id: str = Field(max_length=80)
    tags: dict[str, Any] = Field(
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    )
    received_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
        description="Hora de llegada al almacén (riesgo R7: relojes desincronizados).",
    )


_IMMUTABILITY_DDL = (
    f"""
    CREATE OR REPLACE FUNCTION {TABLE_NAME}_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION '{TABLE_NAME} es de solo escritura: los eventos no se modifican ni se borran';
    END;
    $$
    """,
    f"""
    CREATE TRIGGER {TABLE_NAME}_no_update_delete
    BEFORE UPDATE OR DELETE ON {TABLE_NAME}
    FOR EACH ROW EXECUTE FUNCTION {TABLE_NAME}_immutable()
    """,
    f"ALTER TABLE {TABLE_NAME} ENABLE ROW LEVEL SECURITY",
)

# Solo al crear la tabla (`create_all`), y solo en PostgreSQL: SQLite de los tests no tiene plpgsql.
for _statement in _IMMUTABILITY_DDL:
    event.listen(
        TelemetryEventRecord.__table__,
        "after_create",
        DDL(_statement).execute_if(dialect="postgresql"),
    )


def to_row(telemetry_event: TelemetryEvent) -> dict[str, Any]:
    """Contrato envelope → fila. `properties` llega ya filtrado por el allowlist."""
    return {
        "id": telemetry_event.event_id,
        "event_type": telemetry_event.event_type,
        "timestamp": datetime.fromisoformat(telemetry_event.timestamp),
        "service": telemetry_event.source,
        "user_id": telemetry_event.user_id,
        "session_id": telemetry_event.session_id,
        "tags": telemetry_event.properties,
    }


def store_events(session: Session, events: Iterable[TelemetryEvent]) -> int:
    """Inserta el lote en una sola sentencia y una sola transacción.

    Devuelve cuántas filas son nuevas; un `eventId` ya guardado (reintento) se omite.
    """
    rows = [to_row(telemetry_event) for telemetry_event in events]
    if not rows:
        return 0
    dialect = session.get_bind().dialect.name
    insert = postgresql_insert if dialect == "postgresql" else sqlite_insert
    statement = insert(TelemetryEventRecord.__table__).values(rows).on_conflict_do_nothing(
        index_elements=["id"]
    )
    try:
        result = session.execute(statement)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return result.rowcount


class ApiEventBuffer:
    """Sumidero de `telemetry.emit`: acumula y persiste en bloque con `flush()`.

    Un fallo del almacén nunca llega a la respuesta: el evento ya quedó en el
    log `trackflow.telemetry` y aquí solo se registra cuántos se perdieron.
    """

    def __init__(self) -> None:
        self._pending: list[TelemetryEvent] = []
        self._lock = threading.Lock()
        self._warned_not_configured = False

    def __call__(self, telemetry_event: TelemetryEvent) -> None:
        with self._lock:
            self._pending.append(telemetry_event)

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def flush(self) -> None:
        with self._lock:
            events, self._pending = self._pending, []
        if not events:
            return
        try:
            with Session(get_engine()) as session:
                stored = store_events(session, events)
        except DatabaseNotConfiguredError:
            if not self._warned_not_configured:
                logger.warning("Falta DATABASE_URL: los eventos de la API solo quedan en el log.")
                self._warned_not_configured = True
            return
        except SQLAlchemyError as error:
            logger.warning(
                "No se guardaron %s eventos de la API en %s (%s).",
                len(events),
                TABLE_NAME,
                type(error).__name__,
            )
            return
        logger.info("Eventos de la API guardados en %s: %s de %s.", TABLE_NAME, stored, len(events))


api_event_buffer = ApiEventBuffer()
