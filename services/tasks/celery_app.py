"""Cola de tareas asíncronas de TrackFlow: instancia de Celery sobre Redis.

Productor / consumidor:

    Cliente → API (encola y responde 202) → Redis (broker) → worker de Celery → Redis (resultado)

- La API solo **encola** (`apply_async`); nunca ejecuta una tarea en su proceso.
- El worker es un proceso aparte (`celery -A services.tasks.celery_app worker`):
  parar la API no lo detiene, y parar el worker no pierde mensajes (siguen en Redis).
- Redis es broker y result backend a la vez; la URL sale de `REDIS_URL`.

Reglas que aplica esta configuración:

- **Mensajes ligeros:** JSON con identificadores (p. ej. `run_id`, `week_start`), nunca lotes de datos.
- **ACK tras éxito:** `task_acks_late` + `task_reject_on_worker_lost`: si el worker muere a
  mitad, el mensaje vuelve a la cola. `worker_prefetch_multiplier = 1` evita que un worker
  acapare mensajes que no está procesando.
- **Timeout siempre:** límite duro y blando por defecto; cada tarea puede fijar el suyo.
- **Reintentos con backoff y DLQ:** ver `services/tasks/pipeline.py` y `services/tasks/dead_letter.py`.

Logs: logger `trackflow.tasks`, una línea por inicio y fin de cada intento con `task_id`,
intento, estado y duración; los fallos añaden el error completo con su traza.
"""

import logging
import os
import time
from typing import Any

from celery import Celery, signals
from celery.backends.redis import RedisBackend


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_QUEUE = "default"
DEAD_LETTER_QUEUE = "dead_letter"

# Por defecto, ninguna tarea corre más de 30 minutos (aviso a los 25).
TASK_SOFT_TIME_LIMIT_SECONDS = 25 * 60
TASK_TIME_LIMIT_SECONDS = 30 * 60

logger = logging.getLogger("trackflow.tasks")


def redis_url() -> str:
    return os.getenv("REDIS_URL", "").strip() or DEFAULT_REDIS_URL


class PublishOnlyRedisBackend(RedisBackend):
    """Backend Redis que no suscribe al productor al resultado de cada tarea que encola.

    Por defecto, `apply_async` abre una suscripción pub/sub por tarea para un posible `.get()`.
    La API nunca espera (consulta `GET /tasks/{id}`), y con Redis caído esa suscripción se
    reintentaba más de un minuto y acababa en `RuntimeError` en lugar de un `503` inmediato.
    `.get()` sigue funcionando: se suscribe al empezar a esperar.
    """

    def on_task_call(self, producer: Any, task_id: str) -> None:
        return None


celery_app = Celery(
    "trackflow",
    broker=redis_url(),
    # `<clase>+<url>`: Celery resuelve el backend por su ruta de importación.
    backend=f"services.tasks.celery_app:PublishOnlyRedisBackend+{redis_url()}",
    include=["services.tasks.pipeline", "services.tasks.dead_letter"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # `GET /tasks/{id}` distingue `pending` (en cola) de `started` (en un worker).
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=TASK_SOFT_TIME_LIMIT_SECONDS,
    task_time_limit=TASK_TIME_LIMIT_SECONDS,
    task_default_queue=DEFAULT_QUEUE,
    task_routes={"tasks.record_dead_letter": {"queue": DEAD_LETTER_QUEUE}},
    # Nombre, args e intentos en el backend: Flower y `GET /tasks/{id}` los muestran.
    result_extended=True,
    result_expires=24 * 60 * 60,
    # Eventos para Flower sin tener que activarlos a mano.
    worker_send_task_events=True,
    task_send_sent_event=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        # Un mensaje sin ACK vuelve a la cola tras este tiempo: tiene que superar el límite duro
        # de una tarea y la espera más larga del backoff, o se ejecutaría dos veces.
        "visibility_timeout": 2 * 60 * 60,
        # La API no se queda colgada si Redis no responde: falla rápido y responde 503.
        "socket_connect_timeout": 3,
        "socket_timeout": 5,
    },
    redis_socket_connect_timeout=3,
    redis_socket_timeout=5,
    broker_connection_timeout=3,
)


# ---------------------------------------------------------------------------
# Logging de cada intento: task_id, intento, estado y duración
# ---------------------------------------------------------------------------

_started_at: dict[str, float] = {}


def attempt_of(task: Any) -> int:
    """Número de intento (1 = primera ejecución)."""
    return int(getattr(task.request, "retries", 0) or 0) + 1


def log_task(level: int, task_id: str, task_name: str, attempt: int, status: str, message: str = "", *args: Any, **kwargs: Any) -> None:
    logger.log(
        level,
        f"task_id=%s task=%s attempt=%s status=%s {message}".rstrip(),
        task_id,
        task_name,
        attempt,
        status,
        *args,
        **kwargs,
    )


@signals.task_prerun.connect
def _log_task_started(task_id: str, task: Any, **_: Any) -> None:
    _started_at[task_id] = time.perf_counter()
    log_task(logging.INFO, task_id, task.name, attempt_of(task), "started")


@signals.task_postrun.connect
def _log_task_finished(task_id: str, task: Any, retval: Any = None, state: str | None = None, **_: Any) -> None:
    started = _started_at.pop(task_id, None)
    duration_ms = int((time.perf_counter() - started) * 1000) if started is not None else -1
    status = (state or "unknown").lower()
    attempt = attempt_of(task)
    if status == "success":
        log_task(logging.INFO, task_id, task.name, attempt, status, "duration_ms=%s", duration_ms)
    elif status == "retry":
        # `retval` es la excepción `Retry`; `exc` guarda el error original.
        error = getattr(retval, "exc", None) or retval
        log_task(logging.WARNING, task_id, task.name, attempt, status, "duration_ms=%s error=%r", duration_ms, error)
    else:
        error = retval if isinstance(retval, BaseException) else None
        log_task(
            logging.ERROR, task_id, task.name, attempt, status, "duration_ms=%s error=%r", duration_ms, error, exc_info=error
        )


@signals.worker_ready.connect
def _warn_if_failures_are_simulated(**_: Any) -> None:
    from services.tasks.pipeline import simulate_failure_enabled

    if simulate_failure_enabled():
        logger.warning("TASKS_SIMULATE_FAILURE activo: el pipeline semanal fallará siempre (solo para demos).")
