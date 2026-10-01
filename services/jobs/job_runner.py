"""Control de estado de los jobs en segundo plano: tabla `job_runs`.

Una fila por ejecución de un job sobre una fecha objetivo, con la máquina de
estados canónica:

    pending → processing → completed
                         ↘ failed

- `pending`: la fila se crea antes de empezar.
- `processing`: se marca antes de hacer ningún trabajo. Es el lock: mientras
  exista una fila `processing` de un job, otra instancia no arranca. El índice
  único parcial `job_runs_one_active` (como mucho una fila `pending` o
  `processing` por job) hace atómica la toma del lock cuando dos instancias
  arrancan a la vez; no hay tabla ni columna de lock aparte.
- `completed` / `failed`: estado final; libera el lock. Cualquier excepción
  (también `KeyboardInterrupt` y `SystemExit`, p. ej. un SIGTERM) deja la fila
  en `failed` con su mensaje, nunca en `processing`.
- Idempotencia por `(job_name, target_date)`: si ya hay una fila `completed`
  para esa fecha, el job no se repite.

Si el proceso muere sin pasar por Python (SIGKILL, OOM, caída de la máquina),
la fila activa caduca a `failed` tras `stale_after` en la siguiente ejecución.

`job_runs` es la capa de orquestación (export CSV, disparo del pipeline, lock
e idempotencia del script). No sustituye a `reporting.pipeline_runs`, que
registra las fases internas del ETL.

Este módulo no importa nada de FastAPI ni de `services/api`: lo usan procesos
independientes de la API (`scripts/nightly_export.py`).
"""

import logging
import re
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Index,
    MetaData,
    Table,
    Text,
    Uuid,
    exists,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.types import JSON


JOB_STATUSES = ("pending", "processing", "completed", "failed")
ACTIVE_STATUSES = ("pending", "processing")
DEFAULT_STALE_AFTER = timedelta(hours=6)
MAX_ERROR_MESSAGE = 500

Bind = Engine | Connection

logger = logging.getLogger("trackflow.jobs")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} in ({', '.join(repr(value) for value in values)})"


metadata = MetaData()

job_runs = Table(
    "job_runs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("job_name", Text, nullable=False),
    Column("target_date", Date, nullable=False),
    Column("status", Text, CheckConstraint(_one_of("status", JOB_STATUSES)), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("error_message", Text),
    # Resultado para soporte: ruta y filas del CSV, código de salida y duración del pipeline.
    Column("details", JSON().with_variant(JSONB(), "postgresql")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_job_runs_job_name_target_date", "job_name", "target_date"),
    # Como mucho una ejecución activa por job: dos instancias simultáneas no pasan las dos.
    Index(
        "job_runs_one_active",
        "job_name",
        unique=True,
        postgresql_where=text(_one_of("status", ACTIVE_STATUSES)),
        sqlite_where=text(_one_of("status", ACTIVE_STATUSES)),
    ),
)


class JobAlreadyRunningError(RuntimeError):
    """Otra instancia del job tiene una fila activa (`pending`/`processing`)."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite devuelve fechas sin zona; todas se guardan en UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


_URL_PATTERN = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)


def describe_error(error: BaseException) -> str:
    """Mensaje guardable en `error_message`, sin credenciales ni cadena de conexión.

    De un error de base de datos solo se guarda la clase del error del driver:
    su texto puede llevar host, usuario o la sentencia SQL con datos.
    """
    error_type = type(error).__name__
    if isinstance(error, SQLAlchemyError):
        original = getattr(error, "orig", None)
        detail = type(original).__name__ if original is not None else error_type
        return f"{error_type}: error de base de datos ({detail}). Detalle en el log del job."
    message = _URL_PATTERN.sub("<url>", str(error)).strip()
    first_line = message.splitlines()[0] if message else ""
    return f"{error_type}: {first_line}"[:MAX_ERROR_MESSAGE] if first_line else error_type


def log_event(
    level: int, job_name: str, target_date: date, status: str, message: str, *args: Any, exc_info: BaseException | None = None
) -> None:
    """Toda línea de log del job lleva su nombre, la fecha objetivo y el estado resultante."""
    logger.log(level, f"job=%s target_date=%s status=%s {message}", job_name, target_date, status, *args, exc_info=exc_info)


def _connect(bind: Bind):
    return bind.connect() if isinstance(bind, Engine) else nullcontext(bind)


def _begin(bind: Bind):
    return bind.begin() if isinstance(bind, Engine) else nullcontext(bind)


# ---------------------------------------------------------------------------
# Esquema
# ---------------------------------------------------------------------------

def ensure_job_runs_table(bind: Bind) -> None:
    """Crea `job_runs` y sus índices si faltan (idempotente).

    Equivale a `services/jobs/migrations/001_create_job_runs.sql`.
    """
    with _begin(bind) as connection:
        metadata.create_all(connection, checkfirst=True)
        if connection.dialect.name == "postgresql":
            connection.execute(text("alter table job_runs alter column id set default gen_random_uuid()"))
            # RLS sin políticas, como `telemetry_events`: solo el propietario
            # (`DATABASE_URL`) lee y escribe; la API REST pública de Supabase, no.
            connection.execute(text("alter table job_runs enable row level security"))


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def has_processing_lock(bind: Bind, job_name: str) -> bool:
    """`True` si otra ejecución del job está en `processing` (el lock está tomado)."""
    statement = select(
        exists().where(job_runs.c.job_name == job_name, job_runs.c.status == "processing")
    )
    with _connect(bind) as connection:
        return bool(connection.execute(statement).scalar())


def has_completed_for_date(bind: Bind, job_name: str, target_date: date) -> bool:
    """`True` si el job ya terminó `completed` para esa fecha objetivo."""
    statement = select(
        exists().where(
            job_runs.c.job_name == job_name,
            job_runs.c.target_date == target_date,
            job_runs.c.status == "completed",
        )
    )
    with _connect(bind) as connection:
        return bool(connection.execute(statement).scalar())


DATETIME_FIELDS = ("started_at", "finished_at", "created_at")


def get_run(bind: Bind, run_id: UUID) -> dict[str, Any] | None:
    with _connect(bind) as connection:
        row = connection.execute(select(job_runs).where(job_runs.c.id == run_id)).mappings().first()
    return _as_dict(row) if row is not None else None


def list_runs(bind: Bind, job_name: str, target_date: date | None = None) -> list[dict[str, Any]]:
    """Ejecuciones del job, de la más antigua a la más reciente."""
    statement = select(job_runs).where(job_runs.c.job_name == job_name)
    if target_date is not None:
        statement = statement.where(job_runs.c.target_date == target_date)
    with _connect(bind) as connection:
        rows = connection.execute(statement.order_by(job_runs.c.created_at, job_runs.c.id)).mappings().all()
    return [_as_dict(row) for row in rows]


def _as_dict(row) -> dict[str, Any]:
    run = dict(row)
    for name in DATETIME_FIELDS:
        run[name] = as_utc(run[name])
    return run


# ---------------------------------------------------------------------------
# Transiciones
# ---------------------------------------------------------------------------

def create_run(bind: Bind, job_name: str, target_date: date) -> UUID:
    """Fila `pending`. Lanza `JobAlreadyRunningError` si otra instancia está activa."""
    run_id = uuid4()
    try:
        with _begin(bind) as connection:
            connection.execute(
                job_runs.insert().values(
                    id=run_id, job_name=job_name, target_date=target_date, status="pending", created_at=utc_now()
                )
            )
    except IntegrityError as error:
        raise JobAlreadyRunningError(f"Ya hay una ejecución activa de {job_name}.") from error
    return run_id


def mark_processing(bind: Bind, run_id: UUID) -> None:
    """`pending` → `processing`, antes de hacer ningún trabajo."""
    with _begin(bind) as connection:
        moved = connection.execute(
            update(job_runs)
            .where(job_runs.c.id == run_id, job_runs.c.status == "pending")
            .values(status="processing", started_at=utc_now())
        ).rowcount
    if moved != 1:
        raise RuntimeError(f"La ejecución {run_id} no existe o ya no está pendiente.")


def mark_completed(bind: Bind, run_id: UUID, details: dict[str, Any] | None = None) -> None:
    """`processing` → `completed`: libera el lock y cuenta para la idempotencia."""
    with _begin(bind) as connection:
        moved = connection.execute(
            update(job_runs)
            .where(job_runs.c.id == run_id, job_runs.c.status == "processing")
            .values(status="completed", finished_at=utc_now(), details=details)
        ).rowcount
    if moved != 1:
        raise RuntimeError(f"La ejecución {run_id} no está en processing.")


def mark_failed(bind: Bind, run_id: UUID, error: BaseException, details: dict[str, Any] | None = None) -> int:
    """`pending`/`processing` → `failed` con el mensaje de la excepción. No-op si ya terminó."""
    with _begin(bind) as connection:
        return connection.execute(
            update(job_runs)
            .where(job_runs.c.id == run_id, job_runs.c.status.in_(ACTIVE_STATUSES))
            .values(status="failed", finished_at=utc_now(), error_message=describe_error(error), details=details)
        ).rowcount


def expire_stale_runs(bind: Bind, job_name: str, stale_after: timedelta = DEFAULT_STALE_AFTER) -> int:
    """Cierra como `failed` las filas activas más antiguas que `stale_after`.

    Solo pasa si el proceso murió sin ejecutar su `finally` (SIGKILL, OOM).
    Sin esto, esa fila bloquearía el job para siempre.
    """
    now = utc_now()
    hours = stale_after.total_seconds() / 3600
    with _begin(bind) as connection:
        return connection.execute(
            update(job_runs)
            .where(
                job_runs.c.job_name == job_name,
                job_runs.c.status.in_(ACTIVE_STATUSES),
                func.coalesce(job_runs.c.started_at, job_runs.c.created_at) < now - stale_after,
            )
            .values(
                status="failed",
                finished_at=now,
                error_message=f"StaleRun: sin terminar tras {hours:g} h; el proceso se interrumpió sin cerrar la fila.",
            )
        ).rowcount


# ---------------------------------------------------------------------------
# Ejecución completa
# ---------------------------------------------------------------------------

Outcome = Literal["completed", "skipped_locked", "skipped_duplicate"]


@dataclass(frozen=True)
class JobResult:
    outcome: Outcome
    run_id: UUID | None = None
    details: dict[str, Any] | None = None


def run_job(
    bind: Engine,
    job_name: str,
    target_date: date,
    work: Callable[[], dict[str, Any] | None],
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> JobResult:
    """Ejecuta `work` una sola vez por `(job_name, target_date)` y con una sola instancia a la vez.

    - Lock tomado (`processing`, o la carrera la gana otra instancia) → `skipped_locked`.
    - Ya `completed` para la fecha → `skipped_duplicate`; `work` no se llama.
    - `work` lanza → la fila queda `failed` con el mensaje y la excepción se propaga.
    """
    stale = expire_stale_runs(bind, job_name, stale_after)
    if stale:
        log_event(logging.WARNING, job_name, target_date, "failed", "%d ejecución(es) zombi cerrada(s) como failed.", stale)

    if has_processing_lock(bind, job_name):
        log_event(logging.INFO, job_name, target_date, "skipped", "Otra instancia está en processing; se aborta.")
        return JobResult("skipped_locked")
    if has_completed_for_date(bind, job_name, target_date):
        log_event(logging.INFO, job_name, target_date, "skipped", "Ya completado para esta fecha; se omite por duplicado.")
        return JobResult("skipped_duplicate")

    try:
        run_id = create_run(bind, job_name, target_date)
    except JobAlreadyRunningError:
        log_event(logging.INFO, job_name, target_date, "skipped", "Otra instancia tomó el lock a la vez; se aborta.")
        return JobResult("skipped_locked")
    log_event(logging.INFO, job_name, target_date, "pending", "Ejecución %s creada.", run_id)

    completed = False
    failure: BaseException | None = None
    try:
        mark_processing(bind, run_id)
        log_event(logging.INFO, job_name, target_date, "processing", "Ejecución %s iniciada.", run_id)
        details = work()
        mark_completed(bind, run_id, details)
        completed = True
        log_event(logging.INFO, job_name, target_date, "completed", "Ejecución %s terminada: %s", run_id, details)
        return JobResult("completed", run_id, details)
    except BaseException as error:
        failure = error
        # La traza completa solo va al log: `error_message` no lleva SQL ni credenciales.
        log_event(
            logging.ERROR, job_name, target_date, "failed", "Ejecución %s falló: %s", run_id, describe_error(error), exc_info=error
        )
        raise
    finally:
        if not completed:
            _close_as_failed(bind, job_name, target_date, run_id, failure)


def _close_as_failed(bind: Engine, job_name: str, target_date: date, run_id: UUID, error: BaseException | None) -> None:
    try:
        mark_failed(bind, run_id, error or RuntimeError("La ejecución terminó sin completarse."))
    except Exception:
        # Sin base de datos no se puede cerrar la fila: la siguiente ejecución
        # la caducará con `expire_stale_runs`.
        logger.exception(
            "job=%s target_date=%s status=processing No se pudo marcar %s como failed.", job_name, target_date, run_id
        )
