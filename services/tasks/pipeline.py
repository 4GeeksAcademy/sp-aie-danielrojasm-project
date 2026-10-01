"""Tarea asíncrona del pipeline semanal de desempeño (`POST /reporting/pipeline-runs`).

Antes, la API ejecutaba el flow de Prefect en su propio proceso (`BackgroundTasks`):
levantar Prefect y recorrer extracción → transformación → carga ocupaba un worker de
Uvicorn durante decenas de segundos. Ahora la API reserva la corrida (`pending`, con el
lock de una corrida activa), encola esta tarea y responde `202` con su `task_id`.

El mensaje solo lleva identificadores: `run_id`, `week_start` (ISO) y `triggered_by`.
El worker lee los eventos de la base de datos él mismo.

Reintentos: `max_retries = 3` (1 ejecución + 3 reintentos) con backoff exponencial
(`TASKS_RETRY_BACKOFF_SECONDS` × 2^n: 30, 60 y 120 s por defecto). Cada intento fallido
cierra su corrida como `failed` en `reporting.pipeline_runs`; el reintento reserva una
corrida nueva (con `retry_of` apuntando a la fallida) para no reutilizar un lock cerrado.
Al agotar los reintentos, el fallo va a la DLQ (`services/tasks/dead_letter.py`) y la
tarea termina en `FAILURE`.
"""

import logging
import os
from datetime import date
from typing import Any
from uuid import UUID

from data.pipelines.pipeline import pipeline_engine, run_weekly_performance, trigger_weekly_performance_run
from data.pipelines.weekly_warehouse_client_performance import runs
from services.tasks.celery_app import attempt_of, celery_app
from services.tasks.dead_letter import send_to_dead_letter


logger = logging.getLogger("trackflow.tasks")

TASK_NAME = "reporting.run_weekly_performance"
MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 30


class PipelineRunFailedError(RuntimeError):
    """El flow terminó, pero no en `Completed` (su error está en `pipeline_runs`)."""


class SimulatedFailureError(RuntimeError):
    """Fallo forzado con `TASKS_SIMULATE_FAILURE` para demostrar reintentos y DLQ."""


def simulate_failure_enabled() -> bool:
    return os.getenv("TASKS_SIMULATE_FAILURE", "").strip().lower() in {"1", "true", "yes"}


def retry_countdown(retries: int) -> int:
    """Espera antes del reintento `retries + 1`: base × 2^retries."""
    try:
        base = int(os.getenv("TASKS_RETRY_BACKOFF_SECONDS", "") or DEFAULT_RETRY_BACKOFF_SECONDS)
    except ValueError:
        base = DEFAULT_RETRY_BACKOFF_SECONDS
    return max(base, 1) * 2**retries


def _close_run(run_id: UUID | None, error: BaseException) -> None:
    """Libera el lock de la corrida del intento (no-op si el flow ya la cerró)."""
    if run_id is None:
        return
    try:
        runs.fail_run(pipeline_engine(), run_id, error)
    except Exception:
        logger.warning("No se pudo cerrar la corrida %s; caducará por heartbeat.", run_id, exc_info=True)


@celery_app.task(
    bind=True,
    name=TASK_NAME,
    max_retries=MAX_RETRIES,
    # Prefect tarda ~10 s en arrancar y el ETL recorre hasta 4 semanas de eventos.
    soft_time_limit=20 * 60,
    time_limit=25 * 60,
)
def run_weekly_performance_task(self, run_id: str, week_start: str | None, triggered_by: str) -> dict[str, Any]:
    week = date.fromisoformat(week_start) if week_start else None
    attempt = attempt_of(self)
    # El primer intento adopta la corrida que reservó la API; los reintentos reservan otra.
    current_run: UUID | None = UUID(run_id) if self.request.retries == 0 else None
    try:
        if current_run is None:
            current_run = trigger_weekly_performance_run(pipeline_engine(), week, triggered_by)
            logger.info("task_id=%s attempt=%s Reintento con la corrida %s.", self.request.id, attempt, current_run)
        if simulate_failure_enabled():
            raise SimulatedFailureError("Fallo simulado (TASKS_SIMULATE_FAILURE) antes de ejecutar el flow.")
        final_state = run_weekly_performance(current_run, week, triggered_by)
        if final_state != "Completed":
            raise PipelineRunFailedError(f"La corrida {current_run} terminó en {final_state}.")
    except Exception as error:
        _close_run(current_run, error)
        if self.request.retries >= self.max_retries:
            send_to_dead_letter(
                self.request.id,
                self.name,
                attempt,
                error,
                {"run_id": run_id, "week_start": week_start, "triggered_by": triggered_by, "last_run_id": str(current_run) if current_run else None},
            )
            raise
        raise self.retry(exc=error, countdown=retry_countdown(self.request.retries))
    return {"run_id": str(current_run), "status": "completed", "week_start": week_start, "attempts": attempt}
