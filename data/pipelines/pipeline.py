"""Pipeline `weekly_warehouse_client_performance` (Prefect 3).

Produce el "Reporte Semanal de Desempeño por Almacén y Cliente" de Thomas (CEO)
y Ana (Head of Warehouse Operations): una fila por `warehouse` × `client_id` ×
semana ISO en `reporting.weekly_warehouse_client_performance`, con volumen de
entrada, throughput de salida, frecuencia de quiebre de stock y tasa de
discrepancia, a partir de los obligatorios de `telemetry_events` (solo lectura).
Diseño: `data/pipelines/PIPELINE_DESIGN.md`.

Ejecución (desde la raíz del monorepo; lee `DATABASE_URL` del entorno o del `.env` raíz):

    uv run python data/pipelines/pipeline.py                         # última semana cerrada + 3 de lookback + semanas con eventos tardíos
    uv run python data/pipelines/pipeline.py --week-start 2026-09-21 # recalcula una semana cerrada concreta
    uv run python data/pipelines/pipeline.py --serve                 # deployment `weekly` con cron 0 2 * * 1 (lunes 02:00 UTC)

Frecuencia prevista: semanal, los lunes a las 02:00 UTC, para que el reporte
esté listo antes del lunes laboral en Zaragoza y Los Ángeles.

El flow principal solo coordina subflows (cada uno con entradas y salidas
explícitas, ejecutable por separado) y el log de la corrida:

    open_pipeline_run
      → extract_business_events_flow          resolve_target_weeks → extract_business_events
      → transform_weekly_kpis_flow            prepare_business_events (caché 1 h)
                                                → compute_inbound_volume · compute_outbound_throughput
                                                  · compute_stockout_frequency · compute_discrepancy_rate
                                                → assemble_weekly_performance → validate_weekly_performance
      → reconcile_with_domain_tables_flow     (opcional, return_state=True) reconcile_with_domain_tables
                                                → detect_capture_drop
      → load_weekly_performance_flow          load_weekly_performance
      → write_eval_snapshot_flow              (opcional, return_state=True) write_eval_snapshot
    close_pipeline_run
"""

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

# `python data/pipelines/pipeline.py` solo pone `data/pipelines` en sys.path; el
# pipeline se importa como paquete desde la raíz (`data.process`, `data.pipelines`).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PIPELINE_DATA_DIR = "weekly_warehouse_client_performance"
# Resultados persistidos de Prefect (caché de la transformación): archivos intermedios en `data/raw/`.
# Tiene que fijarse antes de importar Prefect, que lee su configuración al importarse.
os.environ.setdefault("PREFECT_LOCAL_STORAGE_PATH", str(ROOT / "data" / "raw" / PIPELINE_DATA_DIR / "prefect-results"))

import pandas as pd  # noqa: E402
from prefect import flow, get_run_logger, runtime, task  # noqa: E402
from prefect.states import State  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from data.pipelines.weekly_warehouse_client_performance import runs, storage  # noqa: E402
from data.pipelines.weekly_warehouse_client_performance.database import (  # noqa: E402
    DatabaseNotConfiguredError,
    engine_for,
)
from data.pipelines.weekly_warehouse_client_performance.schema import ensure_schema  # noqa: E402
from data.process.weekly_performance import (  # noqa: E402
    CALCULATION_VERSION,
    CAPTURE_BASELINE_WEEKS,
    CAPTURE_DROP_THRESHOLD,
    CleanBusinessEvents,
    MalformedBusinessEventsError,
    WeeklyPerformance,
    assemble_weekly_rows,
    capture_drops,
    clean_business_events,
    contract_violations,
    current_week_start,
    discrepancy_rate,
    inbound_units_count,
    last_closed_week,
    outbound_orders_count,
    reconcile,
    stockout_events_count,
    total_events,
    week_bounds,
    weekly_performance_from,
)


FLOW_NAME = "weekly-warehouse-client-performance"
DEPLOYMENT_NAME = "weekly"
SCHEDULE_CRON = "0 2 * * 1"  # lunes 02:00 UTC: la semana ISO cerró a las 00:00 en los dos almacenes
EVAL_DIR = ROOT / "data" / "eval" / PIPELINE_DATA_DIR
CONFIG_BLOCK = "weekly-performance-config"
DATABASE_URL_BLOCK = "supabase-database-url"
TRANSFORM_CACHE_TTL = timedelta(hours=1)

logger = logging.getLogger("trackflow.pipelines")


# ---------------------------------------------------------------------------
# Configuración y conexión
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PipelineConfig:
    """Umbrales del pipeline; en producción vienen del block JSON `weekly-performance-config`."""

    lookback_weeks: int = 3
    late_event_horizon_days: int = 90
    stale_after_days: int = 8
    heartbeat_timeout_minutes: int = 15
    capture_drop_threshold: float = CAPTURE_DROP_THRESHOLD


def load_config() -> PipelineConfig:
    """Block JSON si existe (cambiar un umbral no exige desplegar); si no, los valores del diseño."""
    try:
        from prefect.blocks.system import JSON

        values = JSON.load(CONFIG_BLOCK).value
    except Exception:  # sin block (o sin servidor) se usan los valores por defecto
        return PipelineConfig()
    defaults = asdict(PipelineConfig())
    known = {name: type(default)(values[name]) for name, default in defaults.items() if name in values}
    return PipelineConfig(**known)


def database_url() -> str:
    """`DATABASE_URL` del entorno o, en un worker de producción, el block `Secret`."""
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    try:
        from prefect.blocks.system import Secret

        return Secret.load(DATABASE_URL_BLOCK).get()
    except Exception as error:
        raise DatabaseNotConfiguredError(
            f"Falta DATABASE_URL (ni en el entorno ni en el block Secret '{DATABASE_URL_BLOCK}')."
        ) from error


def pipeline_engine() -> Engine:
    return engine_for(database_url())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Errores que no se reintentan
# ---------------------------------------------------------------------------

class InvalidWeekError(ValueError):
    """`week_start` no es el lunes de una semana cerrada."""


class ContractViolationError(RuntimeError):
    """La transformación produjo filas que no cumplen el contrato de la tabla de destino."""


NON_RETRYABLE = (
    InvalidWeekError,
    ContractViolationError,
    MalformedBusinessEventsError,
    runs.PipelineAlreadyRunningError,
    DatabaseNotConfiguredError,
)


def retry_transient_only(task, task_run, state: State) -> bool:
    """Reintentar solo fallos transitorios: un dato inválido falla igual en cada intento."""
    return not isinstance(state.data, NON_RETRYABLE)


def validate_week_start(week_start: date, now: datetime) -> None:
    if week_start.weekday() != 0:
        raise InvalidWeekError(f"week_start debe ser un lunes ({week_start} no lo es).")
    if week_start >= current_week_start(now):
        raise InvalidWeekError(f"La semana {week_start} aún no ha cerrado: nunca se calcula la semana en curso.")



# ---------------------------------------------------------------------------
# Tasks de control (flow principal)
# ---------------------------------------------------------------------------

# Sin reintentos: su único fallo esperable es chocar con otra corrida activa
# (`pipeline_runs_one_active`), y reintentar no lo arregla.
@task(retries=0)
def open_pipeline_run(run_id: UUID | None, trigger: str, triggered_by: str, heartbeat_timeout_minutes: int) -> UUID:
    """Crea el esquema `reporting` si falta y abre la fila de la corrida (o adopta la `pending` del endpoint)."""
    engine = pipeline_engine()
    ensure_schema(engine)
    opened = runs.start_run(
        engine,
        run_id=run_id,
        trigger=trigger,
        triggered_by=triggered_by,
        prefect_flow_run_id=UUID(str(runtime.flow_run.id)),
        heartbeat_timeout=timedelta(minutes=heartbeat_timeout_minutes),
    )
    get_run_logger().info("Corrida %s abierta (%s, %s).", opened, trigger, triggered_by)
    return opened


# 2 reintentos (5 s y 15 s): si no se puede cerrar la fila, la corrida quedaría
# `running` hasta que caduque su heartbeat y bloquearía el siguiente disparo manual.
@task(retries=2, retry_delay_seconds=[5, 15])
def close_pipeline_run(run_id: UUID, summary: dict[str, Any]) -> None:
    """Estado final `completed`, métricas, watermark y duración en `reporting.pipeline_runs`."""
    runs.complete_run(
        pipeline_engine(),
        run_id,
        rows_upserted=summary["rows_upserted"],
        rows_changed=summary["rows_changed"],
        source_watermark=summary["source_watermark"],
    )
    get_run_logger().info("Corrida %s completada.", run_id)


def _checkpoint(run_id: UUID, phase: str, **values: Any) -> None:
    """Fase alcanzada y heartbeat. Best effort: si falla, la siguiente task con BD fallará y reintentará."""
    try:
        runs.checkpoint(pipeline_engine(), run_id, phase=phase, **values)
    except Exception:
        get_run_logger().warning("Corrida %s: no se pudo registrar la fase %s.", run_id, phase)


# ---------------------------------------------------------------------------
# Subflow 1 · Extracción de los eventos de negocio
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TargetWeeks:
    weeks: list[date]
    window_start: datetime
    window_end: datetime
    current_week: date
    # Solo las corridas que buscan eventos tardíos guardan watermark (ver `runs.last_watermark`).
    detects_late_events: bool


@dataclass(frozen=True)
class BusinessEventsExtract:
    """Salida del subflow de extracción: semanas objetivo y sus eventos de `telemetry_events`."""

    target: TargetWeeks
    business_events: pd.DataFrame


# 2 reintentos (10 s y 30 s): una lectura corta que solo falla si Supabase no responde;
# un tercer intento ya retrasaría el reporte sin cambiar el resultado.
@task(retries=2, retry_delay_seconds=[10, 30], retry_condition_fn=retry_transient_only)
def resolve_target_weeks(
    run_id: UUID, week_start: date | None, lookback_weeks: int, late_event_horizon_days: int
) -> TargetWeeks:
    """Semanas a recalcular: la pedida (o la última cerrada), las de lookback y las que tienen eventos tardíos."""
    now = utc_now()
    current_week = current_week_start(now)
    anchor = week_start or last_closed_week(now)
    validate_week_start(anchor, now)
    weeks = {anchor - timedelta(weeks=offset) for offset in range(lookback_weeks + 1)}
    detects_late_events = week_start is None
    if detects_late_events:
        engine = pipeline_engine()
        watermark = runs.last_watermark(engine)
        horizon_start = week_bounds(current_week)[0] - timedelta(days=late_event_horizon_days)
        late = storage.weeks_with_late_events(engine, watermark, horizon_start, week_bounds(current_week)[0])
        weeks.update(late)
        get_run_logger().info(
            "Corrida %s: %d semanas con eventos posteriores al watermark %s.", run_id, len(late), watermark
        )
    ordered = sorted(weeks)
    return TargetWeeks(
        weeks=ordered,
        window_start=week_bounds(ordered[0])[0],
        window_end=week_bounds(ordered[-1])[1],
        current_week=current_week,
        detects_late_events=detects_late_events,
    )


# 3 reintentos con espera exponencial (30 s, 60 s, 120 s): absorben un corte del pooler
# de Supabase o un failover de unos minutos; si sigue caído tras ~3,5 min, el fallo
# no es transitorio y la corrida debe terminar en `failed` para que alguien actúe.
@task(retries=3, retry_delay_seconds=[30, 60, 120], retry_condition_fn=retry_transient_only)
def extract_business_events(run_id: UUID, window_start: datetime, window_end: datetime) -> pd.DataFrame:
    """Los cuatro obligatorios de `telemetry_events` en `[window_start, window_end)` (solo lectura)."""
    events = storage.extract_events(pipeline_engine(), window_start, window_end)
    get_run_logger().info(
        "Corrida %s: %d eventos extraídos de [%s, %s).", run_id, len(events), window_start.isoformat(), window_end.isoformat()
    )
    return events


@flow(name="extract-business-events")
def extract_business_events_flow(
    run_id: UUID, week_start: date | None, lookback_weeks: int, late_event_horizon_days: int
) -> BusinessEventsExtract:
    """Semanas objetivo y eventos `inbound_order_created`, `outbound_order_created`,
    `stock_threshold_triggered` e `inventory_discrepancy_detected` de su ventana."""
    target = resolve_target_weeks(run_id, week_start, lookback_weeks, late_event_horizon_days)
    _checkpoint(
        run_id,
        "extract",
        weeks_requested=target.weeks,
        window_start=target.window_start,
        window_end=target.window_end,
    )
    events = extract_business_events(run_id, target.window_start, target.window_end)
    return BusinessEventsExtract(target=target, business_events=events)


# ---------------------------------------------------------------------------
# Subflow 2 · Transformación en los cuatro KPIs semanales
# ---------------------------------------------------------------------------

def prepare_cache_key(context, parameters: dict[str, Any]) -> str:
    """Clave de caché de `prepare_business_events`.

    La define el conjunto exacto de eventos de entrada (hash de sus `id`
    ordenados), las semanas objetivo y `CALCULATION_VERSION`. Como
    `telemetry_events` es inmutable, los mismos `id` son los mismos datos: el
    resultado solo puede cambiar si llega un evento nuevo (otro hash), si se
    piden otras semanas o si cambian las reglas de cálculo (otra versión).
    """
    events: pd.DataFrame = parameters["business_events"]
    digest = hashlib.sha256()
    digest.update(CALCULATION_VERSION.encode())
    digest.update(",".join(week.isoformat() for week in sorted(parameters["weeks"])).encode())
    digest.update("\n".join(sorted(events["id"].astype(str))).encode())
    return f"{FLOW_NAME}-prepare-{digest.hexdigest()}"


# Caché de 1 hora (`cache_expiration`): una corrida repetida dentro de la hora con
# exactamente los mismos eventos (p. ej. un reintento manual tras un fallo de la
# carga) reutiliza el resultado persistido en lugar de recalcular la parte cara
# (tipos, deduplicación). Pasada la hora se recalcula aunque la clave coincida, para
# no servir un resultado antiguo si se corrige un bug sin subir `CALCULATION_VERSION`.
# Es determinista: sin reintentos, igual que las tasks de KPI.
@task(cache_key_fn=prepare_cache_key, cache_expiration=TRANSFORM_CACHE_TTL, persist_result=True)
def prepare_business_events(business_events: pd.DataFrame, weeks: list[date]) -> CleanBusinessEvents:
    """Tipos, semana ISO, rechazo de filas sin dimensión válida y deduplicación (`data/process/weekly_performance.py`)."""
    return clean_business_events(business_events, weeks)


@task
def compute_inbound_volume(clean_events: pd.DataFrame) -> pd.DataFrame:
    """KPI «Volumen de entrada» → `inbound_units_count`."""
    return inbound_units_count(clean_events)


@task
def compute_outbound_throughput(clean_events: pd.DataFrame) -> pd.DataFrame:
    """KPI «Throughput de salida» → `outbound_orders_count`."""
    return outbound_orders_count(clean_events)


@task
def compute_stockout_frequency(clean_events: pd.DataFrame) -> pd.DataFrame:
    """KPI «Frecuencia de quiebre de stock» → `stockout_events_count`."""
    return stockout_events_count(clean_events)


@task
def compute_discrepancy_rate(clean_events: pd.DataFrame) -> pd.DataFrame:
    """KPI «Tasa de discrepancia» → `discrepancy_events_count` y `discrepancy_rate`."""
    return discrepancy_rate(clean_events)


@task
def assemble_weekly_performance(
    clean: CleanBusinessEvents,
    inbound_volume: pd.DataFrame,
    outbound_throughput: pd.DataFrame,
    stockout_frequency: pd.DataFrame,
    discrepancy: pd.DataFrame,
) -> WeeklyPerformance:
    """Una fila por (warehouse, client_id, week_start) con los cuatro KPIs, más el rastro por semana del log."""
    rows = assemble_weekly_rows(inbound_volume, outbound_throughput, stockout_frequency, discrepancy)
    return weekly_performance_from(clean, rows)


# Sin reintentos: es una comprobación pura; un contrato roto falla igual cada vez y
# debe detener la corrida antes de cargar.
@task(retries=0)
def validate_weekly_performance(run_id: UUID, performance: WeeklyPerformance, weeks: list[date], current_week: date) -> int:
    """Contratos de la tabla de destino: grano único, conteos ≥ 0, tasa coherente, nada de la semana en curso."""
    problems = contract_violations(performance.rows, weeks, current_week)
    if problems:
        raise ContractViolationError("; ".join(problems))
    get_run_logger().info(
        "Corrida %s: %d filas válidas (%d duplicados descartados, %d filas rechazadas).",
        run_id,
        len(performance.rows),
        performance.duplicates_dropped,
        performance.rows_rejected,
    )
    return len(performance.rows)


@flow(name="transform-weekly-warehouse-client-kpis")
def transform_weekly_kpis_flow(
    run_id: UUID, business_events: pd.DataFrame, weeks: list[date], current_week: date
) -> WeeklyPerformance:
    """Volumen de entrada, throughput de salida, frecuencia de quiebre de stock y tasa de
    discrepancia por almacén, cliente y semana, validados contra el contrato de la tabla de destino."""
    _checkpoint(run_id, "transform", events_extracted=len(business_events))
    clean = prepare_business_events(business_events, weeks)
    performance = assemble_weekly_performance(
        clean,
        compute_inbound_volume(clean.events),
        compute_outbound_throughput(clean.events),
        compute_stockout_frequency(clean.events),
        compute_discrepancy_rate(clean.events),
    )
    _checkpoint(
        run_id,
        "validate",
        duplicates_dropped=performance.duplicates_dropped,
        rows_rejected=performance.rows_rejected,
    )
    validate_weekly_performance(run_id, performance, weeks, current_week)
    return performance


# ---------------------------------------------------------------------------
# Subflow opcional · Reconciliación con las tablas de dominio y caída de captura
# ---------------------------------------------------------------------------

# Opcional: 2 reintentos (10 s y 30 s) para un corte breve; si se agotan, el flow
# principal registra la reconciliación como `unavailable` y sigue con la carga.
@task(retries=2, retry_delay_seconds=[10, 30])
def reconcile_with_domain_tables(
    run_id: UUID, performance: WeeklyPerformance, weeks: list[date], window_start: datetime, window_end: datetime
) -> dict[date, dict]:
    """Compara los KPIs con `stock_entries`, `stock_exits` e `inventory_counts` (detecta eventos perdidos)."""
    movements = storage.read_domain_movements(pipeline_engine(), window_start, window_end)
    result = reconcile(performance.rows, movements, weeks)
    gaps = [week.isoformat() for week, detail in result.items() if detail["status"] == "gap"]
    if gaps:
        get_run_logger().warning("Corrida %s: eventos y movimientos no cuadran en %s.", run_id, ", ".join(gaps))
    return result


# 2 reintentos (10 s y 30 s), como la reconciliación: una lectura corta de
# `pipeline_run_weeks`. Si se agotan, la semana se carga sin el dato de captura.
@task(retries=2, retry_delay_seconds=[10, 30])
def detect_capture_drop(run_id: UUID, performance: WeeklyPerformance, threshold: float) -> dict[date, dict]:
    """Eventos de cada semana frente a la media de las 4 semanas anteriores ya cargadas (sección 11 del diseño)."""
    weekly = {week: total_events(counts) for week, counts in performance.events_by_type.items()}
    first = min(weekly) - timedelta(weeks=CAPTURE_BASELINE_WEEKS)
    history = storage.loaded_event_totals(pipeline_engine(), first, max(weekly))
    result = capture_drops(weekly, history, threshold=threshold)
    dropped = [week.isoformat() for week, detail in result.items() if detail["dropped"]]
    if dropped:
        get_run_logger().warning(
            "Corrida %s: eventos por debajo del %d %% de la media de las %d semanas anteriores en %s.",
            run_id,
            round(threshold * 100),
            CAPTURE_BASELINE_WEEKS,
            ", ".join(dropped),
        )
    return result


@flow(name="reconcile-with-domain-tables")
def reconcile_with_domain_tables_flow(
    run_id: UUID,
    performance: WeeklyPerformance,
    weeks: list[date],
    window_start: datetime,
    window_end: datetime,
    capture_drop_threshold: float,
) -> dict[date, dict]:
    """Por semana: `ok`/`gap` frente a los movimientos reales y, si hay historial, la señal `capture`.

    Una caída de captura con `gap` apunta a eventos perdidos; con `ok`, a menos actividad real.
    """
    result = reconcile_with_domain_tables(run_id, performance, weeks, window_start, window_end)
    capture_state = detect_capture_drop(run_id, performance, capture_drop_threshold, return_state=True)
    if not capture_state.is_completed():
        get_run_logger().warning("Corrida %s: caída de captura no evaluada (%s).", run_id, capture_state.message)
        return result
    capture = capture_state.result()
    return {week: {**detail, "capture": capture[week]} if week in capture else detail for week, detail in result.items()}


# ---------------------------------------------------------------------------
# Subflow 3 · Carga en `reporting.weekly_warehouse_client_performance`
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LoadResult:
    rows_upserted: int
    rows_changed: int


# 3 reintentos con espera exponencial (30 s, 60 s, 120 s), como la extracción: cada
# semana es una transacción con upsert, así que reintentar nunca duplica ni deja una
# semana a medias, y las semanas ya confirmadas por esta corrida no se repiten.
@task(retries=3, retry_delay_seconds=[30, 60, 120], retry_condition_fn=retry_transient_only)
def load_weekly_performance(
    run_id: UUID, performance: WeeklyPerformance, weeks: list[date], reconciliation: dict[date, dict]
) -> LoadResult:
    """Upsert por `unique (warehouse, client_id, week_start)`, una transacción por semana."""
    logger = get_run_logger()
    engine = pipeline_engine()
    already_loaded = storage.loaded_weeks(engine, run_id)
    rows_by_week = {week: rows for week, rows in performance.rows.groupby("week_start")} if not performance.rows.empty else {}
    upserted = changed = 0
    for week in weeks:
        rows = rows_by_week.get(week, performance.rows.iloc[0:0])
        if week in already_loaded:
            upserted += len(rows)
            continue
        week_log = {
            "events_by_type": performance.events_by_type.get(week, {}),
            "reconciliation": json.loads(json.dumps(reconciliation.get(week, {}), default=str)),
            "source_max_received_at": performance.max_received_at.get(week),
        }
        now = utc_now()
        try:
            with engine.begin() as connection:
                week_changed = storage.upsert_week(connection, rows, now)
                storage.record_week(
                    connection,
                    run_id,
                    week,
                    status="loaded",
                    rows_upserted=len(rows),
                    rows_changed=week_changed,
                    loaded_at=now,
                    **week_log,
                )
        except Exception:
            # La transacción de la semana ya hizo rollback; se deja constancia y se reintenta.
            try:
                with engine.begin() as connection:
                    storage.record_week(connection, run_id, week, status="failed", **week_log)
            except Exception:
                logger.warning("Corrida %s: no se pudo marcar la semana %s como fallida.", run_id, week)
            raise
        upserted += len(rows)
        changed += week_changed
        logger.info("Corrida %s: semana %s cargada (%d filas, %d cambiadas).", run_id, week, len(rows), week_changed)
    return LoadResult(rows_upserted=upserted, rows_changed=changed)


@flow(name="load-weekly-warehouse-client-performance")
def load_weekly_performance_flow(
    run_id: UUID, performance: WeeklyPerformance, weeks: list[date], reconciliation: dict[date, dict]
) -> LoadResult:
    """Publica los KPIs validados en `reporting.weekly_warehouse_client_performance` y una fila por semana en `pipeline_run_weeks`."""
    _checkpoint(run_id, "load")
    return load_weekly_performance(run_id, performance, weeks, reconciliation)


# ---------------------------------------------------------------------------
# Subflow opcional · Snapshot de validación
# ---------------------------------------------------------------------------

# Sin reintentos: escribir un JSON local solo falla por disco o permisos, y
# reintentar no lo arregla. Es opcional: su fallo no afecta a los KPIs publicados.
@task(retries=0)
def write_eval_snapshot(run_id: UUID, summary: dict[str, Any], reconciliation: dict[date, dict]) -> str:
    """Snapshot de validación de la corrida en `data/eval/weekly_warehouse_client_performance/<run_id>.json`."""
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    path = EVAL_DIR / f"{run_id}.json"
    payload = {**summary, "reconciliation": {week.isoformat(): detail for week, detail in reconciliation.items()}}
    path.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    return str(path)


@flow(name="write-eval-snapshot")
def write_eval_snapshot_flow(run_id: UUID, summary: dict[str, Any], reconciliation: dict[date, dict]) -> str:
    """Resumen de la corrida y reconciliación por semana en `data/eval/`, para revisar a mano un número publicado."""
    return write_eval_snapshot(run_id, summary, reconciliation)


# ---------------------------------------------------------------------------
# Flow principal
# ---------------------------------------------------------------------------

def record_flow_failure(flow, flow_run, state: State) -> None:
    """Hook `on_failure`/`on_crashed`/`on_cancellation`: estado final y error en `pipeline_runs`."""
    status = "crashed" if state.is_crashed() else "cancelled" if state.is_cancelled() else "failed"
    error: BaseException | None = None
    try:
        result = state.result(raise_on_failure=False)
        error = result if isinstance(result, BaseException) else None
    except Exception:  # el resultado puede no estar disponible (crash)
        error = None
    try:
        runs.fail_flow_run(pipeline_engine(), flow_run.id, status=status, error=error, message=state.message)
    except Exception:
        logger.exception("No se pudo registrar el fallo del flow run %s.", flow_run.id)


def run_summary(
    run_id: UUID,
    trigger: str,
    triggered_by: str,
    extract: BusinessEventsExtract,
    performance: WeeklyPerformance,
    loaded: LoadResult,
) -> dict[str, Any]:
    """Resumen de la corrida: métricas de `pipeline_runs`, snapshot de eval y salida de la CLI."""
    target, events = extract.target, extract.business_events
    watermark = pd.to_datetime(events["received_at"], utc=True).max() if not events.empty else None
    return {
        "run_id": str(run_id),
        "trigger": trigger,
        "triggered_by": triggered_by,
        "weeks": [week.isoformat() for week in target.weeks],
        "window": [target.window_start.isoformat(), target.window_end.isoformat()],
        "events_extracted": len(events),
        "duplicates_dropped": performance.duplicates_dropped,
        "rows_rejected": performance.rows_rejected,
        "rows_upserted": loaded.rows_upserted,
        "rows_changed": loaded.rows_changed,
        "source_watermark": (
            watermark.to_pydatetime() if target.detects_late_events and watermark is not None and pd.notna(watermark) else None
        ),
        "events_by_type": {week.isoformat(): counts for week, counts in performance.events_by_type.items()},
    }


@flow(
    name=FLOW_NAME,
    on_failure=[record_flow_failure],
    on_crashed=[record_flow_failure],
    on_cancellation=[record_flow_failure],
)
def weekly_warehouse_client_performance_flow(
    week_start: date | None = None,
    lookback_weeks: int | None = None,
    trigger: Literal["schedule", "manual"] = "manual",
    triggered_by: str = "cli",
    run_id: UUID | None = None,
) -> dict[str, Any]:
    """Extracción → transformación → carga del reporte semanal, con log de corrida en `reporting.pipeline_runs`.

    Sin `week_start`: última semana cerrada + `lookback_weeks` (3) + semanas con
    eventos tardíos. Con `week_start`: esa semana (y `lookback_weeks` anteriores si se indica).
    """
    logger = get_run_logger()
    config = load_config()
    lookback = lookback_weeks if lookback_weeks is not None else (config.lookback_weeks if week_start is None else 0)

    run_id = open_pipeline_run(run_id, trigger, triggered_by, config.heartbeat_timeout_minutes)
    extract = extract_business_events_flow(run_id, week_start, lookback, config.late_event_horizon_days)
    target = extract.target
    performance = transform_weekly_kpis_flow(run_id, extract.business_events, target.weeks, target.current_week)

    # Fallo manejado explícitamente: sin reconciliación los KPIs siguen siendo
    # correctos (salen de los eventos); solo se pierde el aviso de eventos perdidos.
    reconciliation_state = reconcile_with_domain_tables_flow(
        run_id,
        performance,
        target.weeks,
        target.window_start,
        target.window_end,
        config.capture_drop_threshold,
        return_state=True,
    )
    if reconciliation_state.is_completed():
        reconciliation = reconciliation_state.result()
    else:
        logger.warning(
            "Corrida %s: reconciliación no disponible (%s); se carga igualmente.", run_id, reconciliation_state.message
        )
        reconciliation = {week: {"status": "unavailable"} for week in target.weeks}

    loaded = load_weekly_performance_flow(run_id, performance, target.weeks, reconciliation)
    summary = run_summary(run_id, trigger, triggered_by, extract, performance, loaded)

    # Paso opcional: si falla, se registra y la corrida termina `completed` igualmente.
    snapshot_state = write_eval_snapshot_flow(run_id, summary, reconciliation, return_state=True)
    if not snapshot_state.is_completed():
        logger.warning("Corrida %s: no se pudo escribir el snapshot de eval (%s).", run_id, snapshot_state.message)

    close_pipeline_run(run_id, summary)
    return summary


# ---------------------------------------------------------------------------
# Entradas para `services/reporting` y la línea de comandos
# ---------------------------------------------------------------------------

def trigger_weekly_performance_run(bind: Engine, week_start: date | None, triggered_by: str) -> UUID:
    """Disparo manual: valida la semana y reserva la corrida `pending` (lock incluido).

    Lanza `InvalidWeekError` o `runs.PipelineAlreadyRunningError`. La corrida
    se ejecuta después con `run_weekly_performance(run_id, ...)`.
    """
    now = utc_now()
    if week_start is not None:
        validate_week_start(week_start, now)
    ensure_schema(bind)
    return runs.create_pending_run(
        bind,
        triggered_by=triggered_by,
        weeks_requested=[week_start or last_closed_week(now)],
    )


def run_weekly_performance(run_id: UUID, week_start: date | None, triggered_by: str) -> str:
    """Ejecuta el flow para una corrida ya reservada y devuelve el nombre de su estado final."""
    state = weekly_warehouse_client_performance_flow(
        week_start=week_start, trigger="manual", triggered_by=triggered_by, run_id=run_id, return_state=True
    )
    if not state.is_completed():
        # Si el flow cae antes de adoptar la corrida `pending`, el hook no la
        # encuentra por `prefect_flow_run_id`: se cierra aquí (no-op si ya está cerrada).
        result = state.result(raise_on_failure=False)
        error = result if isinstance(result, BaseException) else RuntimeError(state.message or state.name)
        runs.fail_run(pipeline_engine(), run_id, error)
    return state.name


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reporte Semanal de Desempeño por Almacén y Cliente.")
    parser.add_argument("--week-start", type=date.fromisoformat, help="Lunes (YYYY-MM-DD) de una semana cerrada.")
    parser.add_argument("--lookback-weeks", type=int, help="Semanas anteriores a recalcular (3 por defecto sin --week-start).")
    parser.add_argument("--triggered-by", default="cli", help="Quién lanza la corrida (queda en pipeline_runs).")
    parser.add_argument("--serve", action="store_true", help=f"Sirve el deployment '{DEPLOYMENT_NAME}' con cron {SCHEDULE_CRON} UTC.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    args = _parse_args(argv)
    if args.serve:
        weekly_warehouse_client_performance_flow.serve(
            name=DEPLOYMENT_NAME,
            cron=SCHEDULE_CRON,
            parameters={"trigger": "schedule", "triggered_by": "system:prefect"},
            # Una sola corrida a la vez, además del índice único parcial de `pipeline_runs`.
            global_limit=1,
        )
        return 0
    state = weekly_warehouse_client_performance_flow(
        week_start=args.week_start,
        lookback_weeks=args.lookback_weeks,
        trigger="manual",
        triggered_by=args.triggered_by,
        return_state=True,
    )
    if not state.is_completed():
        print(f"La corrida terminó en {state.name}: {state.message}", file=sys.stderr)
        return 1
    print(json.dumps(state.result(), indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
