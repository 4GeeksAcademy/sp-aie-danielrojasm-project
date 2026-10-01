"""Cálculo del "Reporte Semanal de Desempeño por Almacén y Cliente" (funciones puras).

Convierte los cuatro eventos obligatorios de `telemetry_events` en una fila por
`warehouse` × `client_id` × semana ISO con los KPIs de `CONTEXT-company.md`:

| Columna                     | KPI                            | Regla                                                    |
|-----------------------------|--------------------------------|----------------------------------------------------------|
| `inbound_units_count`       | Volumen de entrada             | Suma de `quantity` de `inbound_order_created`.           |
| `outbound_orders_count`     | Throughput de salida           | Conteo de `outbound_order_created` con `exit_type = dispatch`. |
| `stockout_events_count`     | Frecuencia de quiebre de stock | Conteo de `stock_threshold_triggered` (`low` y `out`).   |
| `discrepancy_events_count`  | Apoyo de la tasa               | Conteo de `inventory_discrepancy_detected`.              |
| `discrepancy_rate`          | Tasa de discrepancia           | `discrepancy_events_count / outbound_orders_count` (4 decimales; 0 sin pedidos). |

Mismo orden que el reporte técnico: convertir tipos → semana ISO → descartar
filas sin dimensión → deduplicar → agrupar → agregar. Sin E/S: con los mismos
eventos devuelve siempre lo mismo (de eso depende la caché de la task de
transformación). Reglas y decisiones en `data/pipelines/PIPELINE_DESIGN.md`, sección 6.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pandas as pd


INBOUND = "inbound_order_created"
OUTBOUND = "outbound_order_created"
STOCKOUT = "stock_threshold_triggered"
DISCREPANCY = "inventory_discrepancy_detected"
EVENT_TYPES = (INBOUND, OUTBOUND, STOCKOUT, DISCREPANCY)

WAREHOUSES = ("los_angeles", "zaragoza")
EXIT_TYPES = ("dispatch", "loss")
CLIENT_ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

# Columnas que devuelve la extracción (claves de `tags` ya separadas).
SOURCE_COLUMNS = (
    "id",
    "event_type",
    "timestamp",
    "received_at",
    "warehouse",
    "client_id",
    "quantity",
    "exit_type",
    "order_id",
    "count_id",
    "product_id",
    "stock_level",
    "triggering_order_id",
)
GRAIN = ["warehouse", "client_id", "week_start"]
COUNT_COLUMNS = [
    "inbound_units_count",
    "outbound_orders_count",
    "stockout_events_count",
    "discrepancy_events_count",
]
KPI_COLUMNS = [*COUNT_COLUMNS, "discrepancy_rate"]
OUTPUT_COLUMNS = [*GRAIN, *KPI_COLUMNS]

# Claves de `events_by_type` (rastro por semana en `reporting.pipeline_run_weeks`).
EVENT_COUNT_KEYS = (
    INBOUND,
    f"{OUTBOUND}_dispatch",
    f"{OUTBOUND}_loss",
    STOCKOUT,
    DISCREPANCY,
)

# Cambiar una regla de cálculo exige subir la versión: forma parte de la clave
# de caché de la transformación y deja inservibles los resultados anteriores.
CALCULATION_VERSION = "1"


@dataclass(frozen=True)
class WeeklyPerformance:
    """Salida de la transformación: filas de la tabla de destino y rastro para el log."""

    rows: pd.DataFrame
    duplicates_dropped: int
    rows_rejected: int
    # Por semana objetivo: eventos que entraron en el cálculo, por tipo.
    events_by_type: dict[date, dict[str, int]] = field(default_factory=dict)
    # Por semana objetivo: mayor `received_at` de sus eventos (`None` si no hubo).
    max_received_at: dict[date, datetime | None] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Semanas ISO (lunes 00:00 UTC)
# ---------------------------------------------------------------------------

def week_start_of(moment: datetime) -> date:
    """Lunes (UTC) de la semana ISO de `moment` (sin zona = UTC)."""
    day = (moment.astimezone(timezone.utc) if moment.tzinfo else moment).date()
    return day - timedelta(days=day.weekday())


def current_week_start(now: datetime) -> date:
    """Semana en curso: nunca se calcula (un número parcial se lee como una caída)."""
    return week_start_of(now)


def last_closed_week(now: datetime) -> date:
    return current_week_start(now) - timedelta(days=7)


def week_bounds(week: date) -> tuple[datetime, datetime]:
    """`[lunes 00:00 UTC, lunes siguiente 00:00 UTC)`."""
    start = datetime.combine(week, time(), tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def _week_start_series(timestamps: pd.Series) -> pd.Series:
    days = timestamps.dt.normalize()
    return (days - pd.to_timedelta(timestamps.dt.weekday, unit="D")).dt.date


# ---------------------------------------------------------------------------
# Transformación
# ---------------------------------------------------------------------------

def _key_text(values: pd.Series) -> pd.Series:
    """Identificadores numéricos (`order_id`, `count_id`...) como texto estable.

    PostgreSQL devuelve `'1842'` (`->>`) y SQLite `1842`; con nulos, Pandas lo
    convertiría en `1842.0`. Todo acaba como `'1842'` o `<NA>`.
    """
    numeric = pd.to_numeric(values, errors="coerce")
    as_text = numeric.astype("Int64").astype("string")
    return as_text.fillna(values.astype("string"))


def _convert_types(events: pd.DataFrame) -> pd.DataFrame:
    events = events.loc[:, list(SOURCE_COLUMNS)].copy()
    # Siempre a datetime UTC antes de agrupar por semana.
    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True)
    events["received_at"] = pd.to_datetime(events["received_at"], utc=True)
    events["quantity"] = pd.to_numeric(events["quantity"], errors="coerce").astype("Int64")
    for name in ("id", "event_type", "warehouse", "client_id", "exit_type", "product_id", "stock_level"):
        events[name] = events[name].astype("string")
    for name in ("order_id", "count_id", "triggering_order_id"):
        events[name] = _key_text(events[name])
    return events


def _valid_rows(events: pd.DataFrame) -> pd.Series:
    """Filas con dimensión y datos de cálculo válidos; el resto nunca se imputa a un cliente."""
    is_inbound = events["event_type"] == INBOUND
    is_outbound = events["event_type"] == OUTBOUND
    valid = (
        events["event_type"].isin(EVENT_TYPES)
        & events["warehouse"].isin(WAREHOUSES)
        & events["client_id"].str.fullmatch(CLIENT_ID_PATTERN)
        & ~(is_inbound & ~(events["quantity"] >= 1))
        & ~(is_outbound & ~events["exit_type"].isin(EXIT_TYPES))
    )
    return valid.fillna(False).astype(bool)


def _business_key(events: pd.DataFrame) -> pd.Series:
    """Clave de negocio de cada evento (tabla de la sección 4 del diseño).

    Si falta alguna parte, la clave es el propio `id`: sin clave completa no se
    puede afirmar que dos eventos sean el mismo hecho.
    """
    kind = events["event_type"]
    key = pd.Series(pd.NA, index=events.index, dtype="string")
    by_order = kind.isin([INBOUND, OUTBOUND])
    key[by_order] = kind[by_order] + ":" + events.loc[by_order, "order_id"]
    stockout = kind == STOCKOUT
    key[stockout] = (
        kind[stockout]
        + ":" + events.loc[stockout, "product_id"]
        + ":" + events.loc[stockout, "warehouse"]
        + ":" + events.loc[stockout, "stock_level"]
        + ":" + events.loc[stockout, "triggering_order_id"]
    )
    discrepancy = kind == DISCREPANCY
    key[discrepancy] = kind[discrepancy] + ":" + events.loc[discrepancy, "count_id"]
    return key.fillna("id:" + events["id"])


def _deduplicate(events: pd.DataFrame) -> pd.DataFrame:
    """Por `id` y por clave de negocio; se conserva el de menor `received_at`."""
    ordered = events.sort_values(["received_at", "id"], kind="stable")
    ordered = ordered.drop_duplicates(subset="id", keep="first")
    ordered = ordered.assign(business_key=_business_key(ordered))
    return ordered.drop_duplicates(subset="business_key", keep="first").drop(columns="business_key")


def _aggregate(events: pd.DataFrame) -> pd.DataFrame:
    kind = events["event_type"]
    measures = events.loc[:, GRAIN].assign(
        inbound_units_count=events["quantity"].where(kind == INBOUND, 0).fillna(0).astype("int64"),
        outbound_orders_count=((kind == OUTBOUND) & (events["exit_type"] == "dispatch")).astype("int64"),
        stockout_events_count=(kind == STOCKOUT).astype("int64"),
        discrepancy_events_count=(kind == DISCREPANCY).astype("int64"),
    )
    rows = measures.groupby(GRAIN, as_index=False, sort=True)[COUNT_COLUMNS].sum()
    outbound = rows["outbound_orders_count"]
    rows["discrepancy_rate"] = np.where(
        outbound > 0, (rows["discrepancy_events_count"] / outbound.where(outbound > 0, 1)).round(4), 0.0
    )
    return rows.loc[:, OUTPUT_COLUMNS].reset_index(drop=True)


def _events_by_type(events: pd.DataFrame, weeks: Sequence[date]) -> dict[date, dict[str, int]]:
    label = events["event_type"].where(
        events["event_type"] != OUTBOUND, OUTBOUND + "_" + events["exit_type"].fillna("unknown")
    )
    counts = events.assign(label=label).groupby(["week_start", "label"]).size()
    return {
        week: {key: int(counts.get((week, key), 0)) for key in EVENT_COUNT_KEYS}
        for week in weeks
    }


def _max_received_at(events: pd.DataFrame, weeks: Sequence[date]) -> dict[date, datetime | None]:
    latest = events.groupby("week_start")["received_at"].max()
    return {
        week: latest[week].to_pydatetime() if week in latest.index and pd.notna(latest[week]) else None
        for week in weeks
    }


def compute_weekly_performance(events: pd.DataFrame, weeks: Sequence[date]) -> WeeklyPerformance:
    """Filas de `reporting.weekly_warehouse_client_performance` para `weeks`.

    Solo cuentan los eventos cuyo `timestamp` cae en una semana objetivo; los
    demás de la ventana leída se ignoran (no son rechazos). Una combinación sin
    eventos esa semana no tiene fila.
    """
    target = sorted(set(weeks))
    if events.empty:
        empty = pd.DataFrame({name: pd.Series(dtype="object") for name in OUTPUT_COLUMNS})
        return WeeklyPerformance(
            rows=empty,
            duplicates_dropped=0,
            rows_rejected=0,
            events_by_type={week: dict.fromkeys(EVENT_COUNT_KEYS, 0) for week in target},
            max_received_at=dict.fromkeys(target),
        )

    events = _convert_types(events)
    events["week_start"] = _week_start_series(events["timestamp"])
    events = events[events["week_start"].isin(target)]

    valid = _valid_rows(events)
    rows_rejected = int((~valid).sum())
    events = events[valid]

    deduplicated = _deduplicate(events)
    return WeeklyPerformance(
        rows=_aggregate(deduplicated),
        duplicates_dropped=len(events) - len(deduplicated),
        rows_rejected=rows_rejected,
        events_by_type=_events_by_type(deduplicated, target),
        max_received_at=_max_received_at(deduplicated, target),
    )


# ---------------------------------------------------------------------------
# Contratos y reconciliación
# ---------------------------------------------------------------------------

def contract_violations(rows: pd.DataFrame, weeks: Sequence[date], current_week: date) -> list[str]:
    """Comprobaciones previas a la carga; una lista vacía significa que se puede cargar."""
    if rows.empty:
        return []
    problems: list[str] = []
    if list(rows.columns) != OUTPUT_COLUMNS:
        problems.append(f"Columnas inesperadas: {list(rows.columns)}.")
        return problems
    duplicated = int(rows.duplicated(subset=GRAIN).sum())
    if duplicated:
        problems.append(f"{duplicated} filas repiten (warehouse, client_id, week_start).")
    if not rows["warehouse"].isin(WAREHOUSES).all():
        problems.append("Hay almacenes fuera de los_angeles/zaragoza.")
    if not rows["client_id"].astype("string").str.fullmatch(CLIENT_ID_PATTERN).fillna(False).all():
        problems.append("Hay client_id que no cumplen el patrón de slug.")
    if not rows["week_start"].isin(set(weeks)).all():
        problems.append("Hay filas de semanas que no se pidieron.")
    if (rows["week_start"] >= current_week).any():
        problems.append("Hay filas de la semana en curso.")
    if (rows[COUNT_COLUMNS] < 0).any().any():
        problems.append("Hay conteos negativos.")
    outbound = rows["outbound_orders_count"]
    expected_rate = np.where(
        outbound > 0, (rows["discrepancy_events_count"] / outbound.where(outbound > 0, 1)).round(4), 0.0
    )
    if not np.allclose(rows["discrepancy_rate"].astype(float), expected_rate):
        problems.append("discrepancy_rate no coincide con discrepancy_events_count / outbound_orders_count.")
    return problems


# Movimientos de las tablas de dominio comparables con cada KPI (la verdad de la operación).
RECONCILED_MEASURES = {
    "inbound_units": "inbound_units_count",
    "dispatched_orders": "outbound_orders_count",
    "discrepancies": "discrepancy_events_count",
}


def reconcile(rows: pd.DataFrame, movements: pd.DataFrame, weeks: Sequence[date]) -> dict[date, dict]:
    """Compara, por semana y almacén, los KPIs con los movimientos reales.

    `movements` trae una fila por movimiento: `measure` (clave de
    `RECONCILED_MEASURES`), `warehouse` (`los_angeles`/`zaragoza`),
    `created_at` y `amount` (unidades o 1). Una diferencia indica eventos
    perdidos (sin outbox) o rechazados; la v1 la reporta, no corrige los KPIs.
    """
    if movements.empty:
        domain = pd.Series(dtype="int64")
    else:
        movements = movements.assign(
            week_start=_week_start_series(pd.to_datetime(movements["created_at"], utc=True))
        )
        domain = movements.groupby(["week_start", "warehouse", "measure"])["amount"].sum()
    if rows.empty:
        reported = pd.Series(dtype="int64")
    else:
        reported = (
            rows.groupby(["week_start", "warehouse"])[list(RECONCILED_MEASURES.values())]
            .sum()
            .rename(columns={column: measure for measure, column in RECONCILED_MEASURES.items()})
            .stack()
        )

    result: dict[date, dict] = {}
    for week in sorted(set(weeks)):
        warehouses: dict[str, dict[str, dict[str, int]]] = {}
        gap = False
        for warehouse in WAREHOUSES:
            measures = {}
            for measure in RECONCILED_MEASURES:
                events = int(reported.get((week, warehouse, measure), 0))
                real = int(domain.get((week, warehouse, measure), 0))
                measures[measure] = {"events": events, "domain": real}
                gap = gap or events != real
            warehouses[warehouse] = measures
        result[week] = {"status": "gap" if gap else "ok", "warehouses": warehouses}
    return result
