"""Tareas asíncronas del flujo de RFPs: análisis (Parte 1) y generación de respuestas (Parte 2).

La API guarda el PDF, crea el ticket en `analizando`, encola `rfp_intake.process_ticket` con el `ticket_id` y
responde `202`. El worker ejecuta el grafo `rfp_intake` (`data/pipelines/rfp_intake/`) y deja el ticket en
`descartado` o `analisis_completo`. En este último caso encola `rfp_intake.generate_responses`, que consume el
handoff de enrutamiento y genera y evalúa la sección de cada departamento. Los mensajes solo llevan el `ticket_id`.

Reintentos: `max_retries = 2` con el mismo backoff que el resto de tareas (`TASKS_RETRY_BACKOFF_SECONDS` × 2^n).
Cada intento fallido deja `last_error` en el ticket, que no cambia de estado; al agotar los reintentos el fallo
va a la DLQ y el ticket se puede reprocesar con `scripts/rfp_intake.py reprocess` o `generate`. Las dos tareas son
idempotentes: un ticket que ya pasó de su etapa no se vuelve a procesar, así que una entrega duplicada (o el
reintento de la Parte 1 tras un fallo al encolar la Parte 2) no repite el trabajo.
"""

from typing import Any

from data.pipelines.rfp_intake.departments import TicketStatus
from data.pipelines.rfp_intake.response_runner import generate_responses
from data.pipelines.rfp_intake.runner import TicketNotFoundError, intake_engine, process_ticket
from services.tasks.celery_app import attempt_of, celery_app
from services.tasks.dead_letter import send_to_dead_letter
from services.tasks.pipeline import retry_countdown


TASK_NAME = "rfp_intake.process_ticket"
GENERATE_TASK_NAME = "rfp_intake.generate_responses"
MAX_RETRIES = 2


@celery_app.task(bind=True, name=TASK_NAME, max_retries=MAX_RETRIES, soft_time_limit=10 * 60, time_limit=12 * 60)
def process_rfp_ticket_task(self, ticket_id: str) -> dict[str, Any]:
    try:
        status = process_ticket(intake_engine(), ticket_id)
        if status == TicketStatus.ANALISIS_COMPLETO.value:
            generate_rfp_responses_task.apply_async(args=[ticket_id], retry=False)
    except TicketNotFoundError:
        # El ticket se borró (recepción cancelada): no hay nada que reintentar.
        return {"ticket_id": ticket_id, "status": "not_found"}
    except Exception as error:
        if self.request.retries >= self.max_retries:
            send_to_dead_letter(self.request.id, self.name, attempt_of(self), error, {"ticket_id": ticket_id})
            raise
        raise self.retry(exc=error, countdown=retry_countdown(self.request.retries))
    return {"ticket_id": ticket_id, "status": status, "attempts": attempt_of(self)}


@celery_app.task(
    bind=True, name=GENERATE_TASK_NAME, max_retries=MAX_RETRIES, soft_time_limit=20 * 60, time_limit=22 * 60
)
def generate_rfp_responses_task(self, ticket_id: str) -> dict[str, Any]:
    try:
        status = generate_responses(intake_engine(), ticket_id)
    except TicketNotFoundError:
        return {"ticket_id": ticket_id, "status": "not_found"}
    except Exception as error:
        if self.request.retries >= self.max_retries:
            send_to_dead_letter(self.request.id, self.name, attempt_of(self), error, {"ticket_id": ticket_id})
            raise
        raise self.retry(exc=error, countdown=retry_countdown(self.request.retries))
    return {"ticket_id": ticket_id, "status": status, "attempts": attempt_of(self)}
