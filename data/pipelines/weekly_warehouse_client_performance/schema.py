"""Esquema `reporting`: destino del pipeline y log de sus corridas.

- `weekly_warehouse_client_performance`: la tabla de `CONTEXT-company.md`, tal
  cual. Su `unique (warehouse, client_id, week_start)` sostiene el upsert.
- `pipeline_runs`: una fila por corrida (estado, fase, métricas, errores).
  Genérica: la reutilizarán los pipelines de inventario, tracking y devoluciones.
- `pipeline_run_weeks`: una fila por corrida y semana (checkpoint de la carga y
  rastro de qué corrida cambió cada número publicado).

Nada de esto vive en `public` ni toca `telemetry_events`. `ensure_schema` es
idempotente y lo ejecuta la primera task de cada corrida. En SQLite (tests) el
esquema es una base adjunta con `ATTACH ... AS reporting` (`database.py`).
"""

import weakref
from datetime import date
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.engine import Connection, Dialect, Engine
from sqlalchemy.types import JSON, TypeDecorator


SCHEMA = "reporting"

RUN_STATUSES = ("pending", "running", "completed", "failed", "crashed", "cancelled")
ACTIVE_STATUSES = ("pending", "running")
RUN_PHASES = ("extract", "transform", "validate", "load", "done")
RUN_TRIGGERS = ("schedule", "manual", "backfill")
WEEK_STATUSES = ("pending", "loaded", "failed")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} in ({', '.join(repr(value) for value in values)})"


class DateList(TypeDecorator[list[date]]):
    """`date[]` en PostgreSQL; lista JSON de fechas ISO en SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Date()))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[date] | None, dialect: Dialect) -> Any:
        if value is None or dialect.name == "postgresql":
            return value
        return [day.isoformat() for day in value]

    def process_result_value(self, value: Any, dialect: Dialect) -> list[date] | None:
        if value is None or dialect.name == "postgresql":
            return value
        return [date.fromisoformat(day) for day in value]


JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
# Numeric sin Decimal: la API sirve floats y SQLite no tiene decimales nativos.
RATE = Numeric(asdecimal=False)

metadata = MetaData(schema=SCHEMA)

weekly_warehouse_client_performance = Table(
    "weekly_warehouse_client_performance",
    metadata,
    # `default gen_random_uuid()` lo añade `ensure_schema` en PostgreSQL; el
    # pipeline genera el id en Python para que también funcione en SQLite.
    Column("id", Uuid, primary_key=True),
    Column("warehouse", Text, nullable=False),
    Column("client_id", Text, nullable=False),
    Column("week_start", Date, nullable=False),
    Column("inbound_units_count", Integer, nullable=False, server_default=text("0")),
    Column("outbound_orders_count", Integer, nullable=False, server_default=text("0")),
    Column("stockout_events_count", Integer, nullable=False, server_default=text("0")),
    Column("discrepancy_events_count", Integer, nullable=False, server_default=text("0")),
    Column("discrepancy_rate", RATE, nullable=False, server_default=text("0")),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("warehouse", "client_id", "week_start"),
)

pipeline_runs = Table(
    "pipeline_runs",
    metadata,
    Column("run_id", Uuid, primary_key=True),
    Column("pipeline_name", Text, nullable=False),
    Column("trigger", Text, CheckConstraint(_one_of("trigger", RUN_TRIGGERS)), nullable=False),
    Column("triggered_by", Text, nullable=False),
    Column("prefect_flow_run_id", Uuid),
    Column("status", Text, CheckConstraint(_one_of("status", RUN_STATUSES)), nullable=False),
    Column("phase", Text, CheckConstraint(_one_of("phase", RUN_PHASES))),
    Column("weeks_requested", DateList, nullable=False),
    Column("window_start", DateTime(timezone=True)),
    Column("window_end", DateTime(timezone=True)),
    Column("source_watermark", DateTime(timezone=True)),
    Column("events_extracted", Integer, nullable=False, server_default=text("0")),
    Column("duplicates_dropped", Integer, nullable=False, server_default=text("0")),
    Column("rows_rejected", Integer, nullable=False, server_default=text("0")),
    Column("rows_upserted", Integer, nullable=False, server_default=text("0")),
    Column("rows_changed", Integer, nullable=False, server_default=text("0")),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("heartbeat_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    Column("duration_ms", Integer),
    Column("error_type", Text),
    Column("error_message", Text),
    Column("retry_of", Uuid, ForeignKey(f"{SCHEMA}.pipeline_runs.run_id")),
    # Como mucho una corrida activa por pipeline: el cron y el disparo manual no se solapan.
    Index(
        "pipeline_runs_one_active",
        "pipeline_name",
        unique=True,
        postgresql_where=text(_one_of("status", ACTIVE_STATUSES)),
        sqlite_where=text(_one_of("status", ACTIVE_STATUSES)),
    ),
)

pipeline_run_weeks = Table(
    "pipeline_run_weeks",
    metadata,
    Column("run_id", Uuid, ForeignKey(f"{SCHEMA}.pipeline_runs.run_id"), nullable=False),
    Column("week_start", Date, nullable=False),
    Column("status", Text, CheckConstraint(_one_of("status", WEEK_STATUSES)), nullable=False),
    Column("events_by_type", JSON_DOCUMENT, nullable=False, server_default=text("'{}'")),
    Column("reconciliation", JSON_DOCUMENT, nullable=False, server_default=text("'{}'")),
    Column("rows_upserted", Integer, nullable=False, server_default=text("0")),
    Column("rows_changed", Integer, nullable=False, server_default=text("0")),
    Column("source_max_received_at", DateTime(timezone=True)),
    Column("loaded_at", DateTime(timezone=True)),
    PrimaryKeyConstraint("run_id", "week_start"),
)

TABLES = (weekly_warehouse_client_performance, pipeline_runs, pipeline_run_weeks)


# Motores en los que este proceso ya creó o comprobó el esquema. Contra Supabase el DDL
# completo cuesta ~1 s; el disparo manual (`202` inmediato) no puede pagarlo en cada petición.
_ensured_engines: "weakref.WeakSet[Engine]" = weakref.WeakSet()


def ensure_schema(bind: Engine | Connection) -> None:
    """Crea lo que falte del esquema `reporting` (idempotente; con un `Engine`, una vez por proceso)."""
    if isinstance(bind, Engine):
        if bind in _ensured_engines:
            return
        with bind.begin() as connection:
            ensure_schema(connection)
        _ensured_engines.add(bind)
        return
    postgresql = bind.dialect.name == "postgresql"
    if postgresql:
        bind.execute(text(f"create schema if not exists {SCHEMA}"))
    metadata.create_all(bind, checkfirst=True)
    if postgresql:
        bind.execute(
            text(
                f"alter table {SCHEMA}.weekly_warehouse_client_performance "
                "alter column id set default gen_random_uuid()"
            )
        )
        # RLS sin políticas, como `telemetry_events`: solo el propietario
        # (`DATABASE_URL`: API y pipeline) lee y escribe; la API REST pública de Supabase, no.
        for table in TABLES:
            bind.execute(text(f"alter table {SCHEMA}.{table.name} enable row level security"))


def has_schema(bind: Engine | Connection) -> bool:
    """`True` si el pipeline ya creó sus tablas (las lecturas de la API no hacen DDL)."""
    inspector = inspect(bind)
    return all(inspector.has_table(table.name, schema=SCHEMA) for table in TABLES)
