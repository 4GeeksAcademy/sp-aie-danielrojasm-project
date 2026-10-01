"""Log de ejecución: lectura y escritura de `reporting.pipeline_runs`.

Cada corrida deja una fila con hora de inicio y fin, registros procesados,
estado final y error capturado (sección 10 del diseño). La usan el flow
(abrir, checkpoints, cerrar) y `services/reporting` (disparo manual y estado
de la última corrida).

Concurrencia: el índice único parcial `pipeline_runs_one_active` admite como
mucho una corrida `pending`/`running` por pipeline. Una corrida sin heartbeat
durante `heartbeat_timeout_minutes` se da por muerta (`crashed`) y libera el lock.
"""

import re
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from data.pipelines.weekly_warehouse_client_performance.schema import (
    ACTIVE_STATUSES,
    pipeline_runs,
)


PIPELINE_NAME = "weekly_warehouse_client_performance"
HEARTBEAT_TIMEOUT = timedelta(minutes=15)
FINAL_STATUSES = ("completed", "failed", "crashed", "cancelled")
MAX_ERROR_MESSAGE = 500

Bind = Engine | Connection


class PipelineAlreadyRunningError(RuntimeError):
    """Ya hay una corrida activa de este pipeline: no se lanza otra."""

    def __init__(self, active_run_id: UUID | None) -> None:
        super().__init__(f"Ya hay una corrida en curso ({active_run_id}).")
        self.active_run_id = active_run_id


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite devuelve fechas sin zona; todas se guardan en UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


_URL_PATTERN = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)


def describe_error(error: BaseException) -> tuple[str, str]:
    """`(error_type, error_message)` sin credenciales ni cadena de conexión.

    De un error de base de datos solo se guarda la clase del error del driver:
    su texto puede llevar host, usuario o la sentencia SQL con datos.
    """
    error_type = type(error).__name__
    if isinstance(error, SQLAlchemyError):
        original = getattr(error, "orig", None)
        detail = type(original).__name__ if original is not None else error_type
        return error_type, f"Error de base de datos ({detail}). Detalle en los logs del flow run."
    message = _URL_PATTERN.sub("<url>", str(error)).strip() or error_type
    return error_type, message.splitlines()[0][:MAX_ERROR_MESSAGE]


# ---------------------------------------------------------------------------
# Apertura
# ---------------------------------------------------------------------------

def _active_run_id(connection: Connection, pipeline_name: str) -> UUID | None:
    return connection.execute(
        select(pipeline_runs.c.run_id).where(
            pipeline_runs.c.pipeline_name == pipeline_name,
            pipeline_runs.c.status.in_(ACTIVE_STATUSES),
        )
    ).scalar()


def _expire_stale_runs(connection: Connection, pipeline_name: str, now: datetime, timeout: timedelta) -> None:
    connection.execute(
        update(pipeline_runs)
        .where(
            pipeline_runs.c.pipeline_name == pipeline_name,
            pipeline_runs.c.status.in_(ACTIVE_STATUSES),
            pipeline_runs.c.heartbeat_at < now - timeout,
        )
        .values(
            status="crashed",
            finished_at=now,
            error_type="HeartbeatTimeout",
            error_message=f"Sin heartbeat durante {int(timeout.total_seconds() // 60)} minutos.",
        )
    )


def _retry_of(connection: Connection, pipeline_name: str) -> UUID | None:
    """La corrida anterior, si terminó mal: la nueva es su recuperación."""
    previous = connection.execute(
        select(pipeline_runs.c.run_id, pipeline_runs.c.status)
        .where(pipeline_runs.c.pipeline_name == pipeline_name, pipeline_runs.c.status.in_(FINAL_STATUSES))
        .order_by(pipeline_runs.c.started_at.desc())
        .limit(1)
    ).first()
    return previous.run_id if previous is not None and previous.status in ("failed", "crashed") else None


def _insert_run(
    bind: Engine,
    *,
    status: str,
    trigger: str,
    triggered_by: str,
    weeks_requested: list[date],
    prefect_flow_run_id: UUID | None,
    pipeline_name: str,
    heartbeat_timeout: timedelta,
) -> UUID:
    run_id = uuid4()
    now = utc_now()
    try:
        with bind.begin() as connection:
            _expire_stale_runs(connection, pipeline_name, now, heartbeat_timeout)
            connection.execute(
                pipeline_runs.insert().values(
                    run_id=run_id,
                    pipeline_name=pipeline_name,
                    trigger=trigger,
                    triggered_by=triggered_by,
                    prefect_flow_run_id=prefect_flow_run_id,
                    status=status,
                    weeks_requested=weeks_requested,
                    started_at=now,
                    heartbeat_at=now,
                    retry_of=_retry_of(connection, pipeline_name),
                )
            )
    except IntegrityError as error:
        with bind.connect() as connection:
            active = _active_run_id(connection, pipeline_name)
        raise PipelineAlreadyRunningError(active) from error
    return run_id


def create_pending_run(
    bind: Engine,
    *,
    triggered_by: str,
    weeks_requested: list[date],
    pipeline_name: str = PIPELINE_NAME,
    heartbeat_timeout: timedelta = HEARTBEAT_TIMEOUT,
) -> UUID:
    """Disparo manual desde la API: reserva el lock antes de lanzar el flow."""
    return _insert_run(
        bind,
        status="pending",
        trigger="manual",
        triggered_by=triggered_by,
        weeks_requested=weeks_requested,
        prefect_flow_run_id=None,
        pipeline_name=pipeline_name,
        heartbeat_timeout=heartbeat_timeout,
    )


def start_run(
    bind: Engine,
    *,
    run_id: UUID | None,
    trigger: str,
    triggered_by: str,
    prefect_flow_run_id: UUID | None,
    pipeline_name: str = PIPELINE_NAME,
    heartbeat_timeout: timedelta = HEARTBEAT_TIMEOUT,
) -> UUID:
    """Pasa a `running` la corrida `pending` del endpoint, o crea una nueva."""
    if run_id is None:
        return _insert_run(
            bind,
            status="running",
            trigger=trigger,
            triggered_by=triggered_by,
            weeks_requested=[],
            prefect_flow_run_id=prefect_flow_run_id,
            pipeline_name=pipeline_name,
            heartbeat_timeout=heartbeat_timeout,
        )
    now = utc_now()
    with bind.begin() as connection:
        adopted = connection.execute(
            update(pipeline_runs)
            .where(pipeline_runs.c.run_id == run_id, pipeline_runs.c.status == "pending")
            .values(status="running", prefect_flow_run_id=prefect_flow_run_id, heartbeat_at=now)
        ).rowcount
    if adopted != 1:
        raise RuntimeError(f"La corrida {run_id} no existe o ya no está pendiente.")
    return run_id


# ---------------------------------------------------------------------------
# Durante y al final de la corrida
# ---------------------------------------------------------------------------

def checkpoint(bind: Engine, run_id: UUID, **values: Any) -> None:
    """Fase alcanzada y métricas parciales; renueva el heartbeat."""
    with bind.begin() as connection:
        connection.execute(
            update(pipeline_runs).where(pipeline_runs.c.run_id == run_id).values(heartbeat_at=utc_now(), **values)
        )


def complete_run(bind: Engine, run_id: UUID, **values: Any) -> None:
    _finish(bind, pipeline_runs.c.run_id == run_id, status="completed", phase="done", **values)


def fail_run(bind: Engine, run_id: UUID, error: BaseException) -> int:
    """Cierra como `failed` una corrida que no llegó a ejecutar el flow."""
    error_type, error_message = describe_error(error)
    return _finish(
        bind, pipeline_runs.c.run_id == run_id, status="failed", error_type=error_type, error_message=error_message
    )


def fail_flow_run(
    bind: Engine, prefect_flow_run_id: UUID, *, status: str, error: BaseException | None, message: str | None
) -> int:
    """Cierra la corrida de un flow run que falló, se canceló o murió.

    Se localiza por `prefect_flow_run_id` porque los hooks de Prefect no ven el
    `run_id` (puede haberse creado dentro del flow). Conserva la `phase`
    alcanzada: es el checkpoint que dice dónde se cayó.
    """
    if error is not None:
        error_type, error_message = describe_error(error)
    else:
        error_type, error_message = status.capitalize(), (message or status)[:MAX_ERROR_MESSAGE]
    return _finish(
        bind,
        pipeline_runs.c.prefect_flow_run_id == prefect_flow_run_id,
        status=status,
        error_type=error_type,
        error_message=error_message,
    )


def _finish(bind: Engine, condition, **values: Any) -> int:
    now = utc_now()
    with bind.begin() as connection:
        rows = connection.execute(
            select(pipeline_runs.c.run_id, pipeline_runs.c.started_at).where(
                condition, pipeline_runs.c.status.in_(ACTIVE_STATUSES)
            )
        ).all()
        for row in rows:
            duration = now - as_utc(row.started_at)
            connection.execute(
                update(pipeline_runs)
                .where(pipeline_runs.c.run_id == row.run_id)
                .values(
                    finished_at=now,
                    heartbeat_at=now,
                    duration_ms=int(duration.total_seconds() * 1000),
                    **values,
                )
            )
    return len(rows)


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------

def last_watermark(bind: Bind, pipeline_name: str = PIPELINE_NAME) -> datetime | None:
    """Watermark de la última corrida completada que buscó eventos tardíos.

    Solo esas corridas lo guardan: una corrida manual de una sola semana no
    recalcula las demás y no puede dar por vistos sus eventos tardíos.
    """
    statement = (
        select(pipeline_runs.c.source_watermark)
        .where(
            pipeline_runs.c.pipeline_name == pipeline_name,
            pipeline_runs.c.status == "completed",
            pipeline_runs.c.source_watermark.is_not(None),
        )
        .order_by(pipeline_runs.c.source_watermark.desc())
        .limit(1)
    )
    with _connect(bind) as connection:
        return as_utc(connection.execute(statement).scalar())


RUN_FIELDS = (
    "run_id",
    "pipeline_name",
    "status",
    "phase",
    "trigger",
    "triggered_by",
    "prefect_flow_run_id",
    "weeks_requested",
    "window_start",
    "window_end",
    "source_watermark",
    "events_extracted",
    "duplicates_dropped",
    "rows_rejected",
    "rows_upserted",
    "rows_changed",
    "started_at",
    "heartbeat_at",
    "finished_at",
    "duration_ms",
    "error_type",
    "error_message",
    "retry_of",
)
DATETIME_FIELDS = ("window_start", "window_end", "source_watermark", "started_at", "heartbeat_at", "finished_at")


def get_latest_run(
    bind: Bind, pipeline_name: str = PIPELINE_NAME, *, stale_after: timedelta = timedelta(days=8), now: datetime | None = None
) -> dict[str, Any] | None:
    """Última corrida del pipeline, más `last_completed_at` y `stale`.

    `stale` es `True` si la última corrida completada tiene más de
    `stale_after` (o nunca hubo una): el reporte del lunes no se ha refrescado.
    """
    now = now or utc_now()
    with _connect(bind) as connection:
        latest = connection.execute(
            select(*(pipeline_runs.c[name] for name in RUN_FIELDS))
            .where(pipeline_runs.c.pipeline_name == pipeline_name)
            .order_by(pipeline_runs.c.started_at.desc())
            .limit(1)
        ).mappings().first()
        if latest is None:
            return None
        last_completed = connection.execute(
            select(pipeline_runs.c.finished_at)
            .where(pipeline_runs.c.pipeline_name == pipeline_name, pipeline_runs.c.status == "completed")
            .order_by(pipeline_runs.c.finished_at.desc())
            .limit(1)
        ).scalar()
    run = dict(latest)
    for name in DATETIME_FIELDS:
        run[name] = as_utc(run[name])
    run["last_completed_at"] = as_utc(last_completed)
    run["stale"] = run["last_completed_at"] is None or now - run["last_completed_at"] > stale_after
    return run


def _connect(bind: Bind):
    return bind.connect() if isinstance(bind, Engine) else nullcontext(bind)
