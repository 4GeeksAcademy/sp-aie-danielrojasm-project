"""`GET /tasks/{task_id}`: estado de una tarea encolada en Celery.

Lee el result backend (Redis); no ejecuta nada. Los estados de Celery se exponen en
minúsculas: `PENDING` → `pending`, `STARTED` → `started`, `RETRY` → `retry`,
`SUCCESS` → `success`, `FAILURE` → `failure` (`REVOKED` también es `failure`).
"""

import logging
from uuid import UUID

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from kombu.exceptions import OperationalError as BrokerError
from redis.exceptions import RedisError

from services.api.security import get_current_user
from services.api.task_models import TaskStatus, TaskStatusRead
from services.jobs.job_runner import describe_error
from services.tasks.celery_app import celery_app


logger = logging.getLogger("trackflow.api")

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(get_current_user)])

QUEUE_UNAVAILABLE_DETAIL = "La cola de tareas no está disponible ahora mismo; vuelve a intentarlo en unos minutos."

CELERY_STATES: dict[str, TaskStatus] = {
    "PENDING": "pending",
    "RECEIVED": "pending",
    "STARTED": "started",
    "RETRY": "retry",
    "SUCCESS": "success",
    "FAILURE": "failure",
    "REVOKED": "failure",
}


@router.get("/{task_id}", response_model=TaskStatusRead, responses={503: {"description": "Redis no responde."}})
def get_task_status(task_id: UUID) -> TaskStatusRead:
    task = AsyncResult(str(task_id), app=celery_app)
    try:
        state = task.state
        outcome = task.result
    except (RedisError, BrokerError, OSError) as error:
        logger.error("No se pudo leer la tarea %s del result backend: %s", task_id, type(error).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE_DETAIL) from error
    task_status = CELERY_STATES.get(state, "pending")
    return TaskStatusRead(
        task_id=str(task_id),
        status=task_status,
        result=outcome if task_status == "success" and isinstance(outcome, dict) else None,
        error=describe_error(outcome) if isinstance(outcome, BaseException) else None,
    )
