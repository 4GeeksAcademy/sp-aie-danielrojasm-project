"""Tareas asíncronas del flujo de RFPs: análisis (Parte 1), generación (Parte 2) y aprobación (Parte 3).

La API guarda el PDF, crea el ticket en `analizando`, encola `rfp_intake.process_ticket` con el `ticket_id` y
responde `202`. El worker ejecuta el grafo `rfp_intake` (`data/pipelines/rfp_intake/`) y deja el ticket en
`descartado` o `analisis_completo`. En este último caso encola `rfp_intake.generate_responses`, que consume el
handoff de enrutamiento y genera y evalúa la sección de cada departamento; al terminar encola
`rfp_intake.start_approval`, que abre la revisión humana de cada sección y deja el grafo de aprobación pausado en su
checkpoint. Cada decisión que registra un responsable en el backoffice llega como `rfp_intake.resume_approval` y
reanuda solo la rama de su departamento. Los mensajes solo llevan el `ticket_id` (y, en el `resume`, la decisión).

Reintentos: `max_retries = 2` con el mismo backoff que el resto de tareas (`TASKS_RETRY_BACKOFF_SECONDS` × 2^n).
Cada intento fallido deja `last_error` en el ticket, que no cambia de estado; al agotar los reintentos el fallo
va a la DLQ y el ticket se puede reprocesar con `scripts/rfp_intake.py reprocess`, `generate` o `approval start`.
Las tareas son idempotentes: un ticket que ya pasó de su etapa no se vuelve a procesar y una decisión que ya no
corresponde a la revisión pendiente se descarta, así que una entrega duplicada no repite el trabajo.
"""

import logging
from typing import Any

from pydantic import ValidationError

from data.pipelines.rfp_intake.approval import InvalidDecisionError
from data.pipelines.rfp_intake.approval_runner import NoPendingReviewError, start_approval, submit_decision
from data.pipelines.rfp_intake.departments import TicketStatus
from data.pipelines.rfp_intake.response_runner import generate_responses
from data.pipelines.rfp_intake.runner import TicketNotFoundError, intake_engine, process_ticket
from services.tasks.celery_app import attempt_of, celery_app
from services.tasks.dead_letter import send_to_dead_letter
from services.tasks.pipeline import retry_countdown


logger = logging.getLogger("trackflow.rfp_intake")

TASK_NAME = "rfp_intake.process_ticket"
GENERATE_TASK_NAME = "rfp_intake.generate_responses"
START_APPROVAL_TASK_NAME = "rfp_intake.start_approval"
RESUME_APPROVAL_TASK_NAME = "rfp_intake.resume_approval"
MAX_RETRIES = 2
APPROVAL_ENTRY_STATUSES = frozenset({TicketStatus.EN_EVALUACION.value, TicketStatus.NEEDS_HUMAN_REVIEW.value})


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
        if status in APPROVAL_ENTRY_STATUSES:
            start_approval_task.apply_async(args=[ticket_id], retry=False)
    except TicketNotFoundError:
        return {"ticket_id": ticket_id, "status": "not_found"}
    except Exception as error:
        if self.request.retries >= self.max_retries:
            send_to_dead_letter(self.request.id, self.name, attempt_of(self), error, {"ticket_id": ticket_id})
            raise
        raise self.retry(exc=error, countdown=retry_countdown(self.request.retries))
    return {"ticket_id": ticket_id, "status": status, "attempts": attempt_of(self)}


@celery_app.task(
    bind=True, name=START_APPROVAL_TASK_NAME, max_retries=MAX_RETRIES, soft_time_limit=20 * 60, time_limit=22 * 60
)
def start_approval_task(self, ticket_id: str) -> dict[str, Any]:
    try:
        status = start_approval(intake_engine(), ticket_id)
    except TicketNotFoundError:
        return {"ticket_id": ticket_id, "status": "not_found"}
    except Exception as error:
        if self.request.retries >= self.max_retries:
            send_to_dead_letter(self.request.id, self.name, attempt_of(self), error, {"ticket_id": ticket_id})
            raise
        raise self.retry(exc=error, countdown=retry_countdown(self.request.retries))
    return {"ticket_id": ticket_id, "status": status, "attempts": attempt_of(self)}


@celery_app.task(
    bind=True, name=RESUME_APPROVAL_TASK_NAME, max_retries=MAX_RETRIES, soft_time_limit=20 * 60, time_limit=22 * 60
)
def resume_approval_task(self, ticket_id: str, department_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    payload = {"ticket_id": ticket_id, "department_id": department_id}
    try:
        status = submit_decision(intake_engine(), ticket_id, department_id, decision)
    except TicketNotFoundError:
        return {**payload, "status": "not_found"}
    except (NoPendingReviewError, InvalidDecisionError, ValidationError) as error:
        # Decisión repetida o que ya no corresponde a la revisión pendiente: no hay nada que reintentar.
        logger.warning("ticket=%s department=%s decisión descartada: %s", ticket_id, department_id, error)
        return {**payload, "status": "ignored", "reason": str(error)[:300]}
    except Exception as error:
        if self.request.retries >= self.max_retries:
            send_to_dead_letter(self.request.id, self.name, attempt_of(self), error, payload)
            raise
        raise self.retry(exc=error, countdown=retry_countdown(self.request.retries))
    return {**payload, "status": status, "attempts": attempt_of(self)}
