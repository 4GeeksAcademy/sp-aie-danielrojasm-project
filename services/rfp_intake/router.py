"""Recepción de RFPs en modo ticket: `/rfps/*` en la API principal (no hay un segundo servicio HTTP).

- `POST /rfps`: valida que el archivo sea un PDF, lo guarda en `data/raw/rfp_intake/`, crea el ticket en
  `analizando`, encola la tarea `rfp_intake.process_ticket` y responde `202` con el `ticket_id`. El grafo nunca corre
  en la API: lo ejecuta el worker de Celery (`services/tasks/rfp_intake.py`).
- `GET /rfps`: últimos tickets, para la vista de recepción.
- `GET /rfps/{ticket_id}`: estado, clasificación, metadatos, aspectos clave por departamento y síntesis; desde
  la Parte 2, el borrador y el `EvaluationResult` de cada sección y, desde la Parte 3, la aprobación de cada
  responsable, la revisión pendiente, los arbitrajes y la traza. La UI lo consulta periódicamente mientras el ticket
  sigue en curso.
- `POST /rfps/{ticket_id}/sections/{department_id}/decision`: registra la decisión del responsable de una sección.
  Se valida contra la revisión pendiente en el checkpoint antes de encolar `rfp_intake.resume_approval`; responde
  `202` y el worker reanuda solo la rama de ese departamento.
- `GET /rfps/{ticket_id}/document`: el documento final (Markdown) cuando el ticket está en `terminado`.

Aquí no hay lógica de agentes: los handlers llaman a `data/pipelines/rfp_intake/runner.py` y `approval_runner.py`.
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from kombu.exceptions import OperationalError as BrokerError
from redis.exceptions import RedisError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from data.pipelines.rfp_intake import approval, approval_runner, runner
from data.pipelines.rfp_intake.departments import DEPARTMENTS, TicketStatus
from data.pipelines.rfp_intake.evaluators import EvaluationResult
from data.pipelines.rfp_intake.schema import RfpMetadata
from services.api.auth_models import User
from services.api.database import DatabaseNotConfiguredError, get_engine
from services.api.security import get_current_user
from services.rfp_intake.models import (
    ApprovalDecisionAccepted,
    DepartmentId,
    DepartmentSectionRead,
    FinalDocumentRead,
    PendingReviewRead,
    RfpClassificationRead,
    RfpMetadataRead,
    RfpReadabilityRead,
    RfpSynthesisRead,
    RfpTicketCreated,
    RfpTicketListItem,
    RfpTicketRead,
)
from services.tasks.rfp_intake import process_rfp_ticket_task, resume_approval_task


logger = logging.getLogger("trackflow.rfp_intake")

router = APIRouter(prefix="/rfps", tags=["rfps"], dependencies=[Depends(get_current_user)])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
PDF_SIGNATURE = b"%PDF-"
RFP_UNAVAILABLE_DETAIL = "La recepción de RFPs no está disponible ahora mismo. Inténtalo de nuevo en unos minutos."
QUEUE_UNAVAILABLE_DETAIL = (
    "No se pudo iniciar el análisis porque la cola de tareas no está disponible; la RFP no se ha registrado. "
    "Vuelve a subirla en unos minutos."
)
NOT_A_PDF_DETAIL = "El archivo tiene que ser un PDF."
EMPTY_FILE_DETAIL = "El archivo está vacío."
TOO_LARGE_DETAIL = "El PDF supera el tamaño máximo de 10 MB."
TICKET_NOT_FOUND_DETAIL = "No existe ninguna RFP con ese ticket."
NO_PENDING_REVIEW_DETAIL = (
    "Esta sección no tiene ninguna revisión esperando decisión: puede que ya se haya registrado. Recarga el ticket."
)
DECISION_QUEUE_DETAIL = (
    "No se pudo registrar la decisión porque la cola de tareas no está disponible. Inténtalo de nuevo en unos minutos."
)
DOCUMENT_NOT_READY_DETAIL = "El documento final todavía no existe: falta la aprobación de alguna sección."


def get_rfp_engine() -> Engine:
    try:
        return get_engine()
    except DatabaseNotConfiguredError as error:
        logger.error("RFPs sin base de datos: %s", error)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, RFP_UNAVAILABLE_DETAIL) from error


def _unavailable(error: SQLAlchemyError, action: str) -> HTTPException:
    # La traza (con host y usuario de la conexión) solo va al log.
    logger.error("No se pudo %s: %s", action, type(error).__name__, exc_info=error)
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, RFP_UNAVAILABLE_DETAIL)


def _read_pdf(file: UploadFile) -> bytes:
    try:
        content = file.file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        file.file.close()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, EMPTY_FILE_DETAIL)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, TOO_LARGE_DETAIL)
    # La extensión y el Content-Type los decide el cliente; la firma del archivo, no.
    if not content.startswith(PDF_SIGNATURE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NOT_A_PDF_DETAIL)
    return content


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RfpTicketCreated,
    responses={
        400: {"description": "El archivo está vacío o no es un PDF."},
        413: {"description": "El PDF supera 10 MB."},
        503: {"description": "PostgreSQL o la cola de tareas no están disponibles; no se crea el ticket."},
    },
)
def upload_rfp(file: UploadFile = File(...), user: User = Depends(get_current_user)) -> RfpTicketCreated:
    content = _read_pdf(file)
    filename = (file.filename or "rfp.pdf").strip()[:255] or "rfp.pdf"
    engine = get_rfp_engine()
    try:
        ticket = runner.receive_upload(engine, content=content, filename=filename, uploaded_by=user.id)
    except SQLAlchemyError as error:
        raise _unavailable(error, "registrar la RFP") from error
    try:
        result = process_rfp_ticket_task.apply_async(args=[ticket.ticket_id], retry=False)
    except (BrokerError, RedisError, OSError) as error:
        logger.error("ticket=%s no se pudo encolar: %s", ticket.ticket_id, type(error).__name__)
        try:
            runner.cancel_upload(engine, ticket.ticket_id)
        except SQLAlchemyError:
            logger.exception("ticket=%s no se pudo cancelar: queda en analizando sin tarea.", ticket.ticket_id)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE_DETAIL) from error
    logger.info("ticket=%s encolado task_id=%s user=%s", ticket.ticket_id, result.id, user.id)
    return RfpTicketCreated(ticket_id=ticket.ticket_id, status=ticket.status, task_id=result.id)


@router.get("", response_model=list[RfpTicketListItem])
def list_rfps() -> list[RfpTicketListItem]:
    try:
        rows = runner.list_tickets(get_rfp_engine())
    except SQLAlchemyError as error:
        raise _unavailable(error, "listar las RFPs") from error
    return [
        RfpTicketListItem(
            ticket_id=ticket.ticket_id,
            status=ticket.status,
            original_filename=ticket.original_filename,
            client_name=metadata.client_name if metadata else None,
            client_country=metadata.client_country if metadata else None,
            departments_needed=metadata.departments_needed if metadata else [],
            attempts=ticket.attempts,
            last_error=ticket.last_error,
            response_handoff_ready=ticket.response_handoff is not None,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )
        for ticket, metadata in rows
    ]


@router.get(
    "/{ticket_id}",
    response_model=RfpTicketRead,
    responses={404: {"description": TICKET_NOT_FOUND_DETAIL}},
)
def get_rfp(ticket_id: str) -> RfpTicketRead:
    engine = get_rfp_engine()
    try:
        detail = runner.get_ticket_detail(engine, ticket_id)
    except runner.TicketNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, TICKET_NOT_FOUND_DETAIL) from error
    except SQLAlchemyError as error:
        raise _unavailable(error, "leer la RFP") from error
    ticket = detail.ticket
    synthesis = ticket.synthesis
    pending = _pending_reviews(engine, ticket_id) if ticket.status == TicketStatus.ESPERANDO_APROBACION.value else {}
    return RfpTicketRead(
        ticket_id=ticket.ticket_id,
        status=ticket.status,
        original_filename=ticket.original_filename,
        attempts=ticket.attempts,
        last_error=ticket.last_error,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        classification=RfpClassificationRead(
            is_rfp=ticket.is_rfp,
            confidence=ticket.classification_confidence or 0.0,
            reason=ticket.classification_reason or "",
        )
        if ticket.is_rfp is not None
        else None,
        metadata=_metadata_read(detail.metadata) if detail.metadata else None,
        sections=[
            DepartmentSectionRead(
                department_id=section.department_id,
                department_name=DEPARTMENTS[section.department_id].name,
                responsible=section.responsible,
                key_aspects=section.key_aspects,
                requested_inputs=section.requested_inputs,
                open_questions=section.open_questions,
                draft_status=section.draft_status,
                iterations=section.iterations,
                draft_content=section.draft_content,
                evaluation=EvaluationResult.model_validate(section.evaluation_results)
                if section.evaluation_results
                else None,
                approval_status=section.approval_status,
                approver=section.approver,
                approved_at=section.approved_at,
                review_round=section.review_round,
                revisions=section.revisions,
                approval_history=section.approval_history,
                pending_review=PendingReviewRead.model_validate(pending[section.department_id])
                if section.department_id in pending
                else None,
            )
            for section in detail.sections
        ],
        synthesis=RfpSynthesisRead(
            summary=synthesis["summary"],
            next_steps=synthesis["next_steps"],
            conflicts=synthesis["conflicts"],
            out_of_scope=synthesis["out_of_scope"],
        )
        if synthesis
        else None,
        handoff_ready=ticket.handoff is not None,
        generation_attempts=ticket.generation_attempts,
        max_iterations=ticket.response_handoff["max_iterations"] if ticket.response_handoff else None,
        response_handoff_ready=ticket.response_handoff is not None,
        approval_attempts=ticket.approval_attempts,
        arbitrations=ticket.arbitrations,
        trace=ticket.trace,
        final_document_ready=detail.final_document is not None,
    )


@router.post(
    "/{ticket_id}/sections/{department_id}/decision",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ApprovalDecisionAccepted,
    responses={
        404: {"description": TICKET_NOT_FOUND_DETAIL},
        409: {"description": "La sección no tiene una revisión pendiente o la decisión no encaja con ella."},
        503: {"description": "PostgreSQL, el checkpoint o la cola de tareas no están disponibles."},
    },
)
def decide_section(
    ticket_id: str,
    department_id: DepartmentId,
    body: approval.DecisionInput,
    user: User = Depends(get_current_user),
) -> ApprovalDecisionAccepted:
    engine = get_rfp_engine()
    try:
        runner.get_ticket_detail(engine, ticket_id)
    except runner.TicketNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, TICKET_NOT_FOUND_DETAIL) from error
    except SQLAlchemyError as error:
        raise _unavailable(error, "leer la RFP") from error
    review = _pending_reviews(engine, ticket_id).get(department_id)
    if review is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_PENDING_REVIEW_DETAIL)
    decision = approval.ApprovalDecision(**body.model_dump(), decided_by=str(user.email))
    try:
        approval.check_against(decision, review)
    except approval.InvalidDecisionError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    try:
        result = resume_approval_task.apply_async(args=[ticket_id, department_id, decision.model_dump()], retry=False)
    except (BrokerError, RedisError, OSError) as error:
        logger.error("ticket=%s no se pudo encolar la decisión: %s", ticket_id, type(error).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DECISION_QUEUE_DETAIL) from error
    logger.info(
        "ticket=%s decisión encolada department=%s decision=%s review_round=%s task_id=%s user=%s",
        ticket_id,
        department_id,
        decision.decision,
        decision.review_round,
        result.id,
        user.id,
    )
    return ApprovalDecisionAccepted(ticket_id=ticket_id, department_id=department_id, task_id=result.id)


@router.get(
    "/{ticket_id}/document",
    response_model=FinalDocumentRead,
    responses={404: {"description": DOCUMENT_NOT_READY_DETAIL}},
)
def get_final_document(ticket_id: str) -> FinalDocumentRead:
    try:
        detail = runner.get_ticket_detail(get_rfp_engine(), ticket_id)
    except runner.TicketNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, TICKET_NOT_FOUND_DETAIL) from error
    except SQLAlchemyError as error:
        raise _unavailable(error, "leer el documento final") from error
    document = detail.final_document
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, DOCUMENT_NOT_READY_DETAIL)
    return FinalDocumentRead(
        ticket_id=document.ticket_id,
        rfp_id=document.rfp_id,
        currency=document.currency,
        generated_at=document.generated_at,
        sections=document.sections,
        content=document.content,
    )


def _pending_reviews(engine: Engine, ticket_id: str) -> dict[str, dict]:
    try:
        return approval_runner.pending_reviews(engine, ticket_id)
    except approval_runner.CheckpointUnavailableError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, RFP_UNAVAILABLE_DETAIL) from error


def _metadata_read(metadata: RfpMetadata) -> RfpMetadataRead:
    return RfpMetadataRead(
        rfp_id=metadata.rfp_id,
        client_name=metadata.client_name,
        client_country=metadata.client_country,
        currency=metadata.currency,
        client_reference=metadata.client_reference,
        services_requested=metadata.services_requested,
        monthly_volume=metadata.monthly_volume,
        deadline=metadata.deadline,
        budget_range=metadata.budget_range,
        departments_needed=metadata.departments_needed,
        readability=RfpReadabilityRead(
            word_count=metadata.word_count,
            estimated_tokens=metadata.estimated_tokens,
            flesch_kincaid_grade=metadata.flesch_kincaid_grade,
            gunning_fog=metadata.gunning_fog,
            flesch_reading_ease=metadata.flesch_reading_ease,
        ),
    )
