"""Tarea asíncrona del análisis de una RFP (`POST /rfps`).

La API guarda el PDF, crea el ticket en `analizando`, encola esta tarea con el `ticket_id` y responde `202`. El
worker ejecuta el grafo `rfp_intake` (`data/pipelines/rfp_intake/`) y deja el ticket en `descartado` o
`analisis_completo`. El mensaje solo lleva el `ticket_id`; el PDF se lee de `data/raw/`.

Reintentos: `max_retries = 2` con el mismo backoff que el resto de tareas (`TASKS_RETRY_BACKOFF_SECONDS` × 2^n).
Cada intento fallido deja `last_error` en el ticket, que sigue en `analizando`; al agotar los reintentos el fallo
va a la DLQ y el ticket se puede reprocesar con `scripts/rfp_intake.py reprocess`. Un ticket que ya no está en
`analizando` no se vuelve a procesar, así que una entrega duplicada no repite el trabajo.
"""

from typing import Any

from data.pipelines.rfp_intake.runner import TicketNotFoundError, intake_engine, process_ticket
from services.tasks.celery_app import attempt_of, celery_app
from services.tasks.dead_letter import send_to_dead_letter
from services.tasks.pipeline import retry_countdown


TASK_NAME = "rfp_intake.process_ticket"
MAX_RETRIES = 2


@celery_app.task(bind=True, name=TASK_NAME, max_retries=MAX_RETRIES, soft_time_limit=10 * 60, time_limit=12 * 60)
def process_rfp_ticket_task(self, ticket_id: str) -> dict[str, Any]:
    try:
        status = process_ticket(intake_engine(), ticket_id)
    except TicketNotFoundError:
        # El ticket se borró (recepción cancelada): no hay nada que reintentar.
        return {"ticket_id": ticket_id, "status": "not_found"}
    except Exception as error:
        if self.request.retries >= self.max_retries:
            send_to_dead_letter(self.request.id, self.name, attempt_of(self), error, {"ticket_id": ticket_id})
            raise
        raise self.retry(exc=error, countdown=retry_countdown(self.request.retries))
    return {"ticket_id": ticket_id, "status": status, "attempts": attempt_of(self)}
