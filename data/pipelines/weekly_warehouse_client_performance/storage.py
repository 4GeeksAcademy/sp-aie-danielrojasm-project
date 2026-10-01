"""E/S del pipeline: lectura de la fuente (solo lectura) y carga en `reporting`.

- `telemetry_events` y las tablas de dominio (`stock_entries`, `stock_exits`,
  `inventory_counts`) solo se leen: aquí no hay ni un INSERT/UPDATE contra
  `public`. Se describen con `table()`/`column()` para no depender de los
  modelos de `services/api`.
- La carga es idempotente: valores absolutos recalculados y upsert por
  `unique (warehouse, client_id, week_start)`, una transacción por semana.
"""

from contextlib import AbstractContextManager, nullcontext
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import DateTime, Integer, String, column, or_, select, table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.types import JSON

from data.pipelines.weekly_warehouse_client_performance.schema import (
    pipeline_run_weeks,
    weekly_warehouse_client_performance,
)
from data.process.weekly_performance import EVENT_TYPES, KPI_COLUMNS, OUTPUT_COLUMNS, total_events, week_start_of


Bind = Engine | Connection

TELEMETRY_EVENTS = table(
    "telemetry_events",
    column("id", String),
    column("event_type", String),
    column("timestamp", DateTime(timezone=True)),
    column("received_at", DateTime(timezone=True)),
    column("service", String),
    column("tags", JSON().with_variant(JSONB(), "postgresql")),
)
STOCK_ENTRIES = table(
    "stock_entries",
    column("warehouse", String),
    column("quantity", Integer),
    column("created_at", DateTime(timezone=True)),
)
STOCK_EXITS = table(
    "stock_exits",
    column("warehouse", String),
    column("exit_type", String),
    column("created_at", DateTime(timezone=True)),
)
INVENTORY_COUNTS = table(
    "inventory_counts",
    column("warehouse", String),
    column("counted_quantity", Integer),
    column("system_quantity", Integer),
    column("created_at", DateTime(timezone=True)),
)

# Códigos de las tablas de dominio → valores de `warehouse` en los eventos.
DOMAIN_WAREHOUSES = {"LA": "los_angeles", "ZGZ": "zaragoza"}

TAG_TEXT = ("warehouse", "client_id", "exit_type", "order_id", "count_id", "product_id", "stock_level", "triggering_order_id")


def _business_events_filter(statement):
    # `service = 'api'` es defensivo: la ingesta ya impide que el navegador envíe obligatorios.
    return statement.where(
        TELEMETRY_EVENTS.c.event_type.in_(EVENT_TYPES),
        TELEMETRY_EVENTS.c.service == "api",
    )


def extract_events(bind: Bind, window_start: datetime, window_end: datetime) -> pd.DataFrame:
    """Los cuatro obligatorios con `timestamp` en `[window_start, window_end)`.

    Una sola consulta; las claves de `tags` se separan en SQL para no traer el
    JSONB entero. Aprovecha los índices de `timestamp` y `event_type`.
    """
    tags = TELEMETRY_EVENTS.c.tags
    statement = _business_events_filter(
        select(
            TELEMETRY_EVENTS.c.id,
            TELEMETRY_EVENTS.c.event_type,
            TELEMETRY_EVENTS.c.timestamp,
            TELEMETRY_EVENTS.c.received_at,
            tags["quantity"].as_integer().label("quantity"),
            *(tags[key].as_string().label(key) for key in TAG_TEXT),
        )
    ).where(
        TELEMETRY_EVENTS.c.timestamp >= window_start,
        TELEMETRY_EVENTS.c.timestamp < window_end,
    )
    return pd.read_sql(statement, bind)


def weeks_with_late_events(
    bind: Bind, watermark: datetime | None, horizon_start: datetime, current_week_start: datetime
) -> list[date]:
    """Semanas cerradas con eventos llegados después de `watermark` (o todas si no hay)."""
    statement = _business_events_filter(select(TELEMETRY_EVENTS.c.timestamp).distinct()).where(
        TELEMETRY_EVENTS.c.timestamp >= horizon_start,
        TELEMETRY_EVENTS.c.timestamp < current_week_start,
    )
    if watermark is not None:
        statement = statement.where(TELEMETRY_EVENTS.c.received_at > watermark)
    with _connection(bind) as connection:
        timestamps = connection.execute(statement).scalars().all()
    return sorted({week_start_of(moment) for moment in timestamps})


def read_domain_movements(bind: Bind, window_start: datetime, window_end: datetime) -> pd.DataFrame:
    """Movimientos reales de la ventana, en el formato de `weekly_performance.reconcile`."""
    entries = select(
        STOCK_ENTRIES.c.warehouse, STOCK_ENTRIES.c.created_at, STOCK_ENTRIES.c.quantity.label("amount")
    ).where(STOCK_ENTRIES.c.created_at >= window_start, STOCK_ENTRIES.c.created_at < window_end)
    dispatches = select(STOCK_EXITS.c.warehouse, STOCK_EXITS.c.created_at).where(
        STOCK_EXITS.c.exit_type == "dispatch",
        STOCK_EXITS.c.created_at >= window_start,
        STOCK_EXITS.c.created_at < window_end,
    )
    discrepancies = select(INVENTORY_COUNTS.c.warehouse, INVENTORY_COUNTS.c.created_at).where(
        INVENTORY_COUNTS.c.counted_quantity != INVENTORY_COUNTS.c.system_quantity,
        INVENTORY_COUNTS.c.created_at >= window_start,
        INVENTORY_COUNTS.c.created_at < window_end,
    )
    with _connection(bind) as connection:
        frames = [
            pd.read_sql(entries, connection).assign(measure="inbound_units"),
            pd.read_sql(dispatches, connection).assign(measure="dispatched_orders", amount=1),
            pd.read_sql(discrepancies, connection).assign(measure="discrepancies", amount=1),
        ]
    movements = pd.concat([frame for frame in frames if not frame.empty] or frames, ignore_index=True)
    movements["warehouse"] = movements["warehouse"].map(DOMAIN_WAREHOUSES)
    return movements.loc[:, ["measure", "warehouse", "created_at", "amount"]]


def _connection(bind: Bind) -> AbstractContextManager[Connection]:
    """Conexión nueva desde un motor, o la del llamante sin cerrarla al salir."""
    return bind.connect() if isinstance(bind, Engine) else nullcontext(bind)


def _insert(connection: Connection, target):
    return (postgresql_insert if connection.dialect.name == "postgresql" else sqlite_insert)(target)


def upsert_week(connection: Connection, rows: pd.DataFrame, computed_at: datetime) -> int:
    """Upsert de las filas de una semana; devuelve cuántas se insertaron o cambiaron.

    Una fila cuyo valor no cambia no se toca (conserva su `computed_at`), así
    que `computed_at` significa "último momento en que este número cambió".
    Todo va en un único `INSERT ... VALUES (...), (...)`: si la transacción
    falla, PostgreSQL deshace la semana entera y nunca queda a medias.
    """
    if rows.empty:
        return 0
    records = [
        {
            "id": uuid4(),
            **{name: _native(value) for name, value in zip(OUTPUT_COLUMNS, row, strict=True)},
            "computed_at": computed_at,
        }
        for row in rows.loc[:, OUTPUT_COLUMNS].itertuples(index=False, name=None)
    ]
    target = weekly_warehouse_client_performance
    statement = _insert(connection, target).values(records)
    current = target.c
    statement = statement.on_conflict_do_update(
        index_elements=["warehouse", "client_id", "week_start"],
        set_={**{name: statement.excluded[name] for name in KPI_COLUMNS}, "computed_at": statement.excluded.computed_at},
        where=or_(*(current[name].is_distinct_from(statement.excluded[name]) for name in KPI_COLUMNS)),
    ).returning(current.id)
    return len(connection.execute(statement).all())


def record_week(
    connection: Connection,
    run_id: UUID,
    week: date,
    *,
    status: str,
    events_by_type: dict[str, int],
    reconciliation: dict[str, Any],
    rows_upserted: int = 0,
    rows_changed: int = 0,
    source_max_received_at: datetime | None = None,
    loaded_at: datetime | None = None,
) -> None:
    """Fila de `pipeline_run_weeks` (upsert: un reintento de la carga la sobrescribe)."""
    values = {
        "status": status,
        "events_by_type": events_by_type,
        "reconciliation": reconciliation,
        "rows_upserted": rows_upserted,
        "rows_changed": rows_changed,
        "source_max_received_at": source_max_received_at,
        "loaded_at": loaded_at,
    }
    statement = _insert(connection, pipeline_run_weeks).values(run_id=run_id, week_start=week, **values)
    connection.execute(
        statement.on_conflict_do_update(index_elements=["run_id", "week_start"], set_=values)
    )


def loaded_weeks(bind: Bind, run_id: UUID) -> set[date]:
    """Semanas ya confirmadas por esta corrida: un reintento de la carga no las repite."""
    statement = select(pipeline_run_weeks.c.week_start).where(
        pipeline_run_weeks.c.run_id == run_id, pipeline_run_weeks.c.status == "loaded"
    )
    with _connection(bind) as connection:
        return set(connection.execute(statement).scalars())


def _native(value: Any) -> Any:
    """Tipos de NumPy/Pandas → tipos de Python para el driver."""
    if hasattr(value, "item"):
        return value.item()
    return value



def loaded_event_totals(bind: Bind, from_week: date, to_week: date) -> dict[date, int]:
    """Eventos por semana en `[from_week, to_week)` según la última carga `loaded` de cada semana."""
    statement = (
        select(pipeline_run_weeks.c.week_start, pipeline_run_weeks.c.events_by_type)
        .where(
            pipeline_run_weeks.c.status == "loaded",
            pipeline_run_weeks.c.week_start >= from_week,
            pipeline_run_weeks.c.week_start < to_week,
        )
        .order_by(pipeline_run_weeks.c.loaded_at)
    )
    with _connection(bind) as connection:
        latest = {week: counts for week, counts in connection.execute(statement)}
    return {week: total_events(counts or {}) for week, counts in latest.items()}
