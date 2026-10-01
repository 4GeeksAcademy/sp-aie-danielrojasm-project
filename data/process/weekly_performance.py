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
filas sin dimensión → deduplicar (`clean_business_events`) → agrupar → agregar
(una función por KPI, unidas por `assemble_weekly_rows`). Sin E/S: con los
mismos eventos devuelve siempre lo mismo (de eso depende la caché de la task de
preparación). Reglas y decisiones en `data/pipelines/PIPELINE_DESIGN.md`, sección 6.
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

# Caída de captura (sección 11 del diseño): eventos de la semana por debajo de
# esta fracción de la media de las `CAPTURE_BASELINE_WEEKS` semanas anteriores.
CAPTURE_DROP_THRESHOLD = 0.5
CAPTURE_BASELINE_WEEKS = 4


class MalformedBusinessEventsError(ValueError):
    """Los eventos no tienen la forma que devuelve la extracción (faltan columnas)."""


@dataclass(frozen=True)
class CleanBusinessEvents:
    """Eventos listos para agregar: tipados, de las semanas objetivo, válidos y sin duplicados."""

    events: pd.DataFrame
    weeks: list[date]
    duplicates_dropped: int
    rows_rejected: int


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


def _require_columns(events: pd.DataFrame, columns: Sequence[str], step: str) -> None:
    missing = [name for name in columns if name not in events.columns]
    if missing:
        raise MalformedBusinessEventsError(f"{step}: faltan las columnas {', '.join(missing)}.")


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


def clean_business_events(events: pd.DataFrame, weeks: Sequence[date]) -> CleanBusinessEvents:
    """Tipos, semana ISO, filtro de semanas objetivo, rechazo de filas inválidas y deduplicación.

    Solo cuentan los eventos cuyo `timestamp` cae en una semana objetivo; los
    demás de la ventana leída se ignoran (no son rechazos). Lanza
    `MalformedBusinessEventsError` si faltan columnas de la extracción.
    """
    target = sorted(set(weeks))
    if events.empty:
        empty = pd.DataFrame({name: pd.Series(dtype="object") for name in [*SOURCE_COLUMNS, "week_start"]})
        return CleanBusinessEvents(events=empty, weeks=target, duplicates_dropped=0, rows_rejected=0)
    _require_columns(events, SOURCE_COLUMNS, "Eventos de telemetry_events")

    events = _convert_types(events)
    events["week_start"] = _week_start_series(events["timestamp"])
    events = events[events["week_start"].isin(target)]

    valid = _valid_rows(events)
    rows_rejected = int((~valid).sum())
    events = events[valid]

    deduplicated = _deduplicate(events)
    return CleanBusinessEvents(
        events=deduplicated.reset_index(drop=True),
        weeks=target,
        duplicates_dropped=len(events) - len(deduplicated),
        rows_rejected=rows_rejected,
    )


# ---------------------------------------------------------------------------
# Un KPI por función: cada una recibe eventos limpios y devuelve una fila por
# combinación (warehouse, client_id, week_start) con actividad de cualquier tipo.
# ---------------------------------------------------------------------------

def _per_combination(events: pd.DataFrame, column: str, values: pd.Series) -> pd.DataFrame:
    measures = events.loc[:, GRAIN].assign(**{column: values.astype("int64")})
    return measures.groupby(GRAIN, as_index=False, sort=True)[[column]].sum()


def _rate(discrepancies: pd.Series, outbound: pd.Series) -> np.ndarray:
    """`discrepancias / pedidos despachados` con 4 decimales; 0 sin pedidos (no se recorta por encima de 1)."""
    return np.where(outbound > 0, (discrepancies / outbound.where(outbound > 0, 1)).round(4), 0.0)


def inbound_units_count(events: pd.DataFrame) -> pd.DataFrame:
    """Volumen de entrada: suma de `quantity` de `inbound_order_created`."""
    _require_columns(events, [*GRAIN, "event_type", "quantity"], "Volumen de entrada")
    quantity = events["quantity"].where(events["event_type"] == INBOUND, 0).fillna(0)
    return _per_combination(events, "inbound_units_count", quantity)


def outbound_orders_count(events: pd.DataFrame) -> pd.DataFrame:
    """Throughput de salida: conteo de `outbound_order_created` con `exit_type = dispatch` (`loss` no es un pedido)."""
    _require_columns(events, [*GRAIN, "event_type", "exit_type"], "Throughput de salida")
    dispatched = (events["event_type"] == OUTBOUND) & (events["exit_type"] == "dispatch")
    return _per_combination(events, "outbound_orders_count", dispatched.fillna(False))


def stockout_events_count(events: pd.DataFrame) -> pd.DataFrame:
    """Frecuencia de quiebre de stock: conteo de `stock_threshold_triggered` (`low` y `out`)."""
    _require_columns(events, [*GRAIN, "event_type"], "Frecuencia de quiebre de stock")
    return _per_combination(events, "stockout_events_count", events["event_type"] == STOCKOUT)


def discrepancy_rate(events: pd.DataFrame) -> pd.DataFrame:
    """Tasa de discrepancia: `discrepancy_events_count / outbound_orders_count` (con su conteo de apoyo)."""
    _require_columns(events, [*GRAIN, "event_type", "exit_type"], "Tasa de discrepancia")
    discrepancies = _per_combination(events, "discrepancy_events_count", events["event_type"] == DISCREPANCY)
    rows = discrepancies.merge(outbound_orders_count(events), on=GRAIN, validate="one_to_one")
    rows["discrepancy_rate"] = _rate(rows["discrepancy_events_count"], rows["outbound_orders_count"])
    return rows.loc[:, [*GRAIN, "discrepancy_events_count", "discrepancy_rate"]]


def assemble_weekly_rows(*kpi_frames: pd.DataFrame) -> pd.DataFrame:
    """Une los KPIs por el grano en las columnas exactas de la tabla de destino."""
    rows = kpi_frames[0]
    for frame in kpi_frames[1:]:
        rows = rows.merge(frame, on=GRAIN, how="outer", validate="one_to_one")
    _require_columns(rows, OUTPUT_COLUMNS, "Filas del reporte semanal")
    rows[COUNT_COLUMNS] = rows[COUNT_COLUMNS].fillna(0).astype("int64")
    rows["discrepancy_rate"] = rows["discrepancy_rate"].fillna(0.0).astype(float)
    return rows.sort_values(GRAIN, kind="stable").loc[:, OUTPUT_COLUMNS].reset_index(drop=True)


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


def weekly_performance_from(clean: CleanBusinessEvents, rows: pd.DataFrame) -> WeeklyPerformance:
    """Filas del reporte y rastro para el log (`events_by_type`, `max_received_at`) por semana objetivo."""
    if clean.events.empty:
        return WeeklyPerformance(
            rows=pd.DataFrame({name: pd.Series(dtype="object") for name in OUTPUT_COLUMNS}),
            duplicates_dropped=clean.duplicates_dropped,
            rows_rejected=clean.rows_rejected,
            events_by_type={week: dict.fromkeys(EVENT_COUNT_KEYS, 0) for week in clean.weeks},
            max_received_at=dict.fromkeys(clean.weeks),
        )
    return WeeklyPerformance(
        rows=rows,
        duplicates_dropped=clean.duplicates_dropped,
        rows_rejected=clean.rows_rejected,
        events_by_type=_events_by_type(clean.events, clean.weeks),
        max_received_at=_max_received_at(clean.events, clean.weeks),
    )


def compute_weekly_performance(events: pd.DataFrame, weeks: Sequence[date]) -> WeeklyPerformance:
    """Filas de `reporting.weekly_warehouse_client_performance` para `weeks` en una sola llamada.

    Es la misma composición que hace el subflow de transformación, task a task.
    Una combinación sin eventos esa semana no tiene fila.
    """
    clean = clean_business_events(events, weeks)
    rows = assemble_weekly_rows(
        inbound_units_count(clean.events),
        outbound_orders_count(clean.events),
        stockout_events_count(clean.events),
        discrepancy_rate(clean.events),
    )
    return weekly_performance_from(clean, rows)


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
    expected_rate = _rate(rows["discrepancy_events_count"], outbound)
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


def total_events(events_by_type: dict[str, int]) -> int:
    return int(sum(events_by_type.values()))


def capture_drops(
    weekly_events: dict[date, int],
    history: dict[date, int],
    threshold: float = CAPTURE_DROP_THRESHOLD,
    baseline_weeks: int = CAPTURE_BASELINE_WEEKS,
) -> dict[date, dict]:
    """Por semana de `weekly_events`: eventos frente a la media de las `baseline_weeks` anteriores.

    `history` son los totales de semanas ya cargadas; si una semana está en los
    dos, manda el recálculo de esta corrida. Sin semanas anteriores no hay base
    (`baseline = None`) y nunca se marca caída. `dropped` solo dice que la
    captura bajó; si además la reconciliación da `gap`, se perdieron eventos.
    """
    known = {**history, **weekly_events}
    result: dict[date, dict] = {}
    for week in sorted(weekly_events):
        previous = [
            known[earlier]
            for earlier in (week - timedelta(weeks=offset) for offset in range(1, baseline_weeks + 1))
            if earlier in known
        ]
        baseline = round(sum(previous) / len(previous), 2) if previous else None
        events = weekly_events[week]
        result[week] = {
            "events": events,
            "baseline": baseline,
            "baseline_weeks": len(previous),
            "dropped": bool(baseline) and events < threshold * baseline,
        }
    return result
