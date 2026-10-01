"""Job nocturno `nightly_export`: backup CSV de la telemetría del día y disparo del pipeline.

Proceso independiente de la API: no importa FastAPI ni `services/api`, abre su
propia conexión con `DATABASE_URL` y lo lanza el cron del contenedor
`scheduler` (`infra/scheduler/crontab`), nunca un hilo de Uvicorn.

Pasos, una sola vez por fecha objetivo (`services/jobs/job_runner.py`):

1. Exporta las filas de `telemetry_events` con `timestamp` en el día objetivo
   (UTC) a `data/raw/telemetry_YYYY-MM-DD.csv`, solo si el archivo no existe.
   El CSV es backup para auditoría y recuperación: el pipeline no lo lee.
2. Lanza como subproceso el pipeline `weekly_warehouse_client_performance`, que
   lee `telemetry_events` desde la base de datos y registra sus fases en
   `reporting.pipeline_runs`.
3. Deja el resultado en `job_runs` (`pending` → `processing` → `completed` | `failed`).

Uso (desde la raíz del monorepo; lee `DATABASE_URL` del entorno o del `.env` raíz):

    uv run python scripts/nightly_export.py                         # ayer (UTC)
    TARGET_DATE=2026-09-28 uv run python scripts/nightly_export.py   # otra fecha cerrada

Códigos de salida: 0 completado u omitido (lock tomado o fecha ya completada),
1 ejecución fallida (la fila queda `failed`), 2 configuración inválida.
"""

import csv
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import date, datetime, time as day_time, timedelta, timezone
from pathlib import Path
from typing import Any

# `python scripts/nightly_export.py` solo pone `scripts/` en sys.path; `services` se importa desde la raíz.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, create_engine, select  # noqa: E402
from sqlalchemy.engine import Engine, make_url  # noqa: E402

from services.jobs import job_runner  # noqa: E402


JOB_NAME = "nightly_export"
RAW_DIR = ROOT / "data" / "raw"
PIPELINE_COMMAND = [sys.executable, "-m", "data.pipelines.pipeline", "--triggered-by", f"job:{JOB_NAME}"]
PIPELINE_TIMEOUT_SECONDS = 60 * 60
CSV_COLUMNS = ("id", "event_type", "timestamp", "service", "user_id", "session_id", "tags", "received_at")
FETCH_BATCH = 1000

logger = logging.getLogger("trackflow.jobs")

# Solo las columnas que se exportan; la tabla la crea y la escribe la API.
telemetry_events = Table(
    "telemetry_events",
    MetaData(),
    Column("id", String, primary_key=True),
    Column("event_type", String),
    Column("timestamp", DateTime(timezone=True)),
    Column("service", String),
    Column("user_id", String),
    Column("session_id", String),
    Column("tags", JSON),
    Column("received_at", DateTime(timezone=True)),
)


class InvalidTargetDateError(ValueError):
    """`TARGET_DATE` no es una fecha `YYYY-MM-DD` de un día ya cerrado."""


class PipelineFailedError(RuntimeError):
    """El subproceso del pipeline terminó con error o superó el tiempo máximo."""


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

def resolve_target_date(now: datetime | None = None) -> date:
    """`TARGET_DATE` (YYYY-MM-DD) o, por defecto, ayer en UTC. Nunca hoy ni el futuro."""
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    raw = os.getenv("TARGET_DATE", "").strip()
    if not raw:
        return today - timedelta(days=1)
    try:
        target = date.fromisoformat(raw)
    except ValueError as error:
        raise InvalidTargetDateError(f"TARGET_DATE debe tener el formato YYYY-MM-DD (recibido: {raw!r}).") from error
    if target >= today:
        # Un día abierto daría un CSV incompleto que, al existir ya, no se volvería a exportar.
        raise InvalidTargetDateError(f"TARGET_DATE {target} aún no ha cerrado en UTC (hoy es {today}).")
    return target


def job_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("Falta DATABASE_URL: configura la cadena de conexión en el .env raíz.")
    if make_url(database_url).get_backend_name() == "sqlite":
        return create_engine(database_url, connect_args={"check_same_thread": False})
    # pool_pre_ping descarta conexiones que el pooler de Supabase haya cerrado.
    return create_engine(database_url, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# Paso 1 · Backup CSV
# ---------------------------------------------------------------------------

def csv_path_for(target_date: date, raw_dir: Path) -> Path:
    return raw_dir / f"telemetry_{target_date.isoformat()}.csv"


def _display_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def _iso_utc(value: datetime | None) -> str:
    return job_runner.as_utc(value).isoformat() if value is not None else ""


def export_telemetry_csv(engine: Engine, target_date: date, raw_dir: Path | None = None) -> dict[str, Any]:
    """Escribe el CSV del día si no existe. Atómico: un fallo a medias no deja un archivo que se dé por bueno."""
    path = csv_path_for(target_date, raw_dir or RAW_DIR)
    if path.exists():
        job_runner.log_event(logging.INFO, JOB_NAME, target_date, "processing", "CSV %s ya existe; no se reexporta.", path.name)
        return {"csv_path": _display_path(path), "csv_created": False}

    start = datetime.combine(target_date, day_time.min, tzinfo=timezone.utc)
    statement = (
        select(*(telemetry_events.c[name] for name in CSV_COLUMNS))
        .where(telemetry_events.c.timestamp >= start, telemetry_events.c.timestamp < start + timedelta(days=1))
        .order_by(telemetry_events.c.timestamp, telemetry_events.c.id)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    rows = 0
    try:
        with engine.connect() as connection, partial.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(CSV_COLUMNS)
            for row in connection.execution_options(yield_per=FETCH_BATCH).execute(statement):
                writer.writerow(
                    (
                        row.id,
                        row.event_type,
                        _iso_utc(row.timestamp),
                        row.service,
                        row.user_id,
                        row.session_id,
                        json.dumps(row.tags, ensure_ascii=False, sort_keys=True),
                        _iso_utc(row.received_at),
                    )
                )
                rows += 1
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
    job_runner.log_event(logging.INFO, JOB_NAME, target_date, "processing", "CSV %s exportado (%d filas).", path.name, rows)
    return {
        "csv_path": _display_path(path),
        "csv_created": True,
        "rows_exported": rows,
    }


# ---------------------------------------------------------------------------
# Paso 2 · Pipeline
# ---------------------------------------------------------------------------

def _last_line(output: str | bytes | None) -> str:
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def run_pipeline(target_date: date, command: list[str] | None = None, timeout: float = PIPELINE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Lanza el pipeline como subproceso y espera a que termine. Error si no sale con código 0."""
    command = command or PIPELINE_COMMAND
    job_runner.log_event(logging.INFO, JOB_NAME, target_date, "processing", "Lanzando el pipeline: %s", " ".join(command[1:]))
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise PipelineFailedError(f"El pipeline superó {timeout:g} s y se detuvo. {_last_line(error.stderr)}".strip()) from error
    duration_ms = int((time.monotonic() - started) * 1000)
    if completed.returncode != 0:
        # Salida completa en el log para soporte; en job_runs, solo la última línea.
        logger.error(
            "job=%s target_date=%s status=processing Salida del pipeline (código %d):\n%s",
            JOB_NAME, target_date, completed.returncode, (completed.stderr or completed.stdout).strip(),
        )
        raise PipelineFailedError(
            f"El pipeline terminó con código {completed.returncode}: {_last_line(completed.stderr) or _last_line(completed.stdout)}"
        )
    job_runner.log_event(logging.INFO, JOB_NAME, target_date, "processing", "Pipeline terminado en %d ms.", duration_ms)
    return {"pipeline_exit_code": completed.returncode, "pipeline_duration_ms": duration_ms}


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def configure_logging() -> None:
    """Una línea por evento con hora UTC ISO 8601: el cron la manda a la salida del contenedor."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _raise_on_sigterm(signum, _frame) -> None:
    # El `finally` de `run_job` cierra la fila como `failed` al parar el contenedor.
    raise SystemExit(128 + signum)


def run(engine: Engine, target_date: date, *, raw_dir: Path | None = None, pipeline_command: list[str] | None = None) -> job_runner.JobResult:
    job_runner.ensure_job_runs_table(engine)

    def work() -> dict[str, Any]:
        details = export_telemetry_csv(engine, target_date, raw_dir or RAW_DIR)
        details.update(run_pipeline(target_date, pipeline_command))
        return details

    return job_runner.run_job(engine, JOB_NAME, target_date, work)


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    configure_logging()
    signal.signal(signal.SIGTERM, _raise_on_sigterm)
    try:
        target_date = resolve_target_date()
        engine = job_engine()
    except (InvalidTargetDateError, RuntimeError) as error:
        logger.error("job=%s target_date=%s status=failed %s", JOB_NAME, os.getenv("TARGET_DATE") or "-", error)
        return 2
    try:
        job_runner.ensure_job_runs_table(engine)
    except Exception as error:
        logger.error("job=%s target_date=%s status=failed Sin acceso a job_runs: %s", JOB_NAME, target_date, job_runner.describe_error(error))
        engine.dispose()
        return 1
    try:
        run(engine, target_date)
    except Exception:
        # `run_job` ya dejó la fila en `failed` y registró el error.
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
