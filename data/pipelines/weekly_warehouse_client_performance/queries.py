"""Lecturas de los KPIs publicados para `services/reporting`.

Solo leen el esquema `reporting`; nunca recalculan. Si el pipeline aún no ha
creado sus tablas, se comportan como "todavía no hay datos" (las lecturas de
la API no hacen DDL).
"""

from contextlib import nullcontext
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine

from data.pipelines.weekly_warehouse_client_performance.runs import as_utc
from data.pipelines.weekly_warehouse_client_performance.schema import (
    has_schema,
    pipeline_run_weeks,
    weekly_warehouse_client_performance,
)


Bind = Engine | Connection

ENTRY_FIELDS = (
    "warehouse",
    "client_id",
    "inbound_units_count",
    "outbound_orders_count",
    "stockout_events_count",
    "discrepancy_events_count",
    "discrepancy_rate",
)


def get_weekly_performance(bind: Bind, week_start: date | None = None) -> dict[str, Any] | None:
    """Todas las combinaciones almacén/cliente de una semana (por defecto, la última cargada).

    Devuelve `None` si esa semana no se ha calculado. Además de `week_start` y
    `entries` (contrato de `CONTEXT-company.md`), añade `computed_at` (el último
    cambio de un número de la semana), `run_id` (la última corrida que cargó la
    semana) y `reconciliation_status` (`ok`, `gap` o `unavailable`).
    """
    target = weekly_warehouse_client_performance
    with bind.connect() if isinstance(bind, Engine) else nullcontext(bind) as connection:
        if not has_schema(connection):
            return None
        if week_start is None:
            # La última semana cargada, aunque no tuviera actividad (cero filas).
            week_start = connection.execute(
                select(func.max(pipeline_run_weeks.c.week_start)).where(pipeline_run_weeks.c.status == "loaded")
            ).scalar()
            if week_start is None:
                return None
        entries = connection.execute(
            select(*(target.c[name] for name in ENTRY_FIELDS), target.c.computed_at)
            .where(target.c.week_start == week_start)
            .order_by(target.c.warehouse, target.c.client_id)
        ).mappings().all()
        last_load = connection.execute(
            select(pipeline_run_weeks.c.run_id, pipeline_run_weeks.c.reconciliation)
            .where(pipeline_run_weeks.c.week_start == week_start, pipeline_run_weeks.c.status == "loaded")
            .order_by(pipeline_run_weeks.c.loaded_at.desc())
            .limit(1)
        ).first()
    if not entries and last_load is None:
        return None
    return {
        "week_start": week_start,
        "computed_at": max((as_utc(entry["computed_at"]) for entry in entries), default=None),
        "run_id": last_load.run_id if last_load is not None else None,
        "reconciliation_status": (last_load.reconciliation or {}).get("status") if last_load is not None else None,
        "entries": [{name: entry[name] for name in ENTRY_FIELDS} for entry in entries],
    }
