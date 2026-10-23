"""Ciclo de vida de la Parte 2 sobre el mismo ticket: del handoff de enrutamiento al handoff hacia la Parte 3.

- **Entrada.** Tickets en `analisis_completo` con `rfp_tickets.handoff` (`rfp_intake.handoff.v1`). Los generadores
  reciben el `ticket_id`, los workstreams y el resumen del synthesizer más los metadatos ya extraídos
  (`rfp_metadata`), nunca el PDF ni `document_markdown`.
- **Progreso.** El ticket pasa a `generando_borrador` al empezar y a `en_evaluación` cuando el primer borrador entra
  en evaluación; desde ahí se queda en `en_evaluación` mientras dure el ciclo generador-evaluador. Cada sección
  guarda en su fila su estado, iteración, borrador, `EvaluationResult` e historial en cuanto cambian
  (`DatabaseProgress`), así que la UI los ve en tiempo real.
- **Salida.** `rfp_tickets.response_handoff` (`rfp_intake.response_handoff.v1`) con el contenido y el
  `EvaluationResult` de cada departamento. Si alguna sección agotó el límite de iteraciones, el ticket queda en
  `needs_human_review` con esa sección marcada; si todas pasan, sigue en `en_evaluación` con el handoff listo (los
  estados de aprobación son de la Parte 3).
- **Fallos.** Como en la Parte 1: `last_error` en el ticket, que se queda en su estado; la tarea se reintenta y un
  reintento vuelve a empezar la generación. Un ticket con `response_handoff` ya no se vuelve a generar.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from data.pipelines.rfp_intake import response_graph
from data.pipelines.rfp_intake.departments import DEPARTMENTS, SectionStatus, TicketStatus
from data.pipelines.rfp_intake.runner import TicketNotFoundError, record_failure
from data.pipelines.rfp_intake.schema import (
    RfpDepartmentSection,
    RfpMetadata,
    RfpTicket,
    ensure_response_schema,
    utc_now,
)
from data.pipelines.rfp_intake.synthesizer import HANDOFF_VERSION


logger = logging.getLogger("trackflow.rfp_intake")

RESPONSE_HANDOFF_VERSION = "rfp_intake.response_handoff.v1"
NEXT_STAGE = "esperando_aprobación"
ENTRY_STATUSES = frozenset(
    {TicketStatus.ANALISIS_COMPLETO.value, TicketStatus.GENERANDO_BORRADOR.value, TicketStatus.EN_EVALUACION.value}
)
SECTION_FIELDS = frozenset({"draft_status", "iterations", "draft_content", "evaluation_results", "evaluation_history"})


class HandoffError(ValueError):
    """El ticket no trae un handoff de la Parte 1 que la Parte 2 sepa leer."""


class DatabaseProgress:
    """Escribe el progreso de cada sección en su fila y adelanta el ticket a `en_evaluación`.

    Los departamentos corren en hilos distintos; el lock serializa las escrituras para que dos secciones no
    actualicen el ticket a la vez.
    """

    def __init__(self, engine: Engine, ticket_id: str) -> None:
        self.engine = engine
        self.ticket_id = ticket_id
        self._lock = threading.Lock()

    def section_update(self, department_id: str, **fields: Any) -> None:
        unknown = set(fields) - SECTION_FIELDS
        if unknown:
            raise ValueError(f"Campos de sección desconocidos: {sorted(unknown)}")
        with self._lock, Session(self.engine) as session:
            section = session.exec(
                select(RfpDepartmentSection).where(
                    RfpDepartmentSection.ticket_id == self.ticket_id,
                    RfpDepartmentSection.department_id == department_id,
                )
            ).one()
            for name, value in fields.items():
                setattr(section, name, value)
            session.add(section)
            ticket = session.get(RfpTicket, self.ticket_id)
            if ticket is not None:
                if (
                    fields.get("draft_status") == SectionStatus.EN_EVALUACION.value
                    and ticket.status == TicketStatus.GENERANDO_BORRADOR.value
                ):
                    ticket.status = TicketStatus.EN_EVALUACION.value
                    logger.info("ticket=%s status=%s", self.ticket_id, ticket.status)
                ticket.updated_at = utc_now()
                session.add(ticket)
            session.commit()


def generate_responses(engine: Engine, ticket_id: str, max_iterations: int | None = None) -> str:
    """Genera y evalúa la sección de cada departamento activo y devuelve el estado final del ticket."""
    ensure_response_schema(engine)
    limit = max_iterations or response_graph.max_iterations_from_env()
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        if ticket.response_handoff is not None or ticket.status not in ENTRY_STATUSES:
            logger.info("ticket=%s en %s: la Parte 2 no lo procesa.", ticket_id, ticket.status)
            return ticket.status
        handoff = _read_handoff(ticket)
        if not handoff["workstreams"]:
            logger.warning("ticket=%s sin departamentos activos: no hay secciones que generar.", ticket_id)
            return ticket.status
        metadata = session.exec(select(RfpMetadata).where(RfpMetadata.ticket_id == ticket_id)).first()
        shared = shared_brief(handoff, metadata)
        for section in session.exec(select(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket_id)):
            section.draft_status = SectionStatus.GENERANDO_BORRADOR.value
            section.iterations = 0
            section.draft_content = section.evaluation_results = None
            section.evaluation_history = []
            session.add(section)
        ticket.status = TicketStatus.GENERANDO_BORRADOR.value
        ticket.generation_attempts += 1
        ticket.last_error = None
        ticket.updated_at = utc_now()
        session.add(ticket)
        session.commit()
        attempt, rfp_id = ticket.generation_attempts, ticket.rfp_id

    logger.info(
        "ticket=%s generation_attempt=%s departments=%s max_iterations=%s inicio de la Parte 2.",
        ticket_id,
        attempt,
        handoff["departments"],
        limit,
    )
    try:
        state = response_graph.run_graph(
            ticket_id, shared, handoff["workstreams"], limit, progress=DatabaseProgress(engine, ticket_id)
        )
        status = _persist_responses(engine, ticket_id, rfp_id, handoff, state["sections"], limit)
    except Exception as error:
        record_failure(engine, ticket_id, error)
        raise
    logger.info("ticket=%s generation_attempt=%s status=%s", ticket_id, attempt, status)
    return status


def shared_brief(handoff: dict[str, Any], metadata: RfpMetadata | None) -> dict[str, Any]:
    """Metadatos compartidos para todos los generadores: lo que ya extrajo la Parte 1, sin el documento."""
    return {
        "client_name": metadata.client_name if metadata else None,
        "client_country": handoff["client_country"],
        "currency": handoff["currency"],
        "services_requested": metadata.services_requested if metadata else [],
        "monthly_volume": metadata.monthly_volume if metadata else None,
        "deadline": metadata.deadline.isoformat() if metadata and metadata.deadline else None,
        "budget_range": metadata.budget_range if metadata else None,
        "summary": handoff["summary"],
        "conflicts": handoff["conflicts"],
    }


def build_response_handoff(
    ticket_id: str,
    rfp_id: str | None,
    status: str,
    handoff: dict[str, Any],
    sections: list[dict[str, Any]],
    max_iterations: int,
) -> dict[str, Any]:
    """Contrato hacia la Parte 3: contenido + `EvaluationResult` por departamento, incluidos los que no pasaron."""
    review = [s["department_id"] for s in sections if s["draft_status"] == SectionStatus.NEEDS_HUMAN_REVIEW.value]
    return {
        "version": RESPONSE_HANDOFF_VERSION,
        "ticket_id": ticket_id,
        "rfp_id": rfp_id,
        "status": status,
        "next_stage": NEXT_STAGE,
        "currency": handoff["currency"],
        "client_country": handoff["client_country"],
        "max_iterations": max_iterations,
        "needs_human_review": review,
        "sections": [
            {
                "department_id": section["department_id"],
                "department_name": DEPARTMENTS[section["department_id"]].name,
                "responsible": DEPARTMENTS[section["department_id"]].responsible,
                "draft_status": section["draft_status"],
                "needs_human_review": section["department_id"] in review,
                "iterations": section["iterations"],
                "draft_content": section["draft_content"],
                "evaluation_result": section["evaluation_results"],
            }
            for section in sections
        ],
    }


def _read_handoff(ticket: RfpTicket) -> dict[str, Any]:
    handoff = ticket.handoff
    if not handoff or handoff.get("version") != HANDOFF_VERSION:
        raise HandoffError(f"El ticket {ticket.ticket_id} no tiene un handoff {HANDOFF_VERSION} de la Parte 1.")
    return handoff


def _persist_responses(
    engine: Engine,
    ticket_id: str,
    rfp_id: str | None,
    handoff: dict[str, Any],
    sections: list[dict[str, Any]],
    max_iterations: int,
) -> str:
    needs_review = any(section["draft_status"] == SectionStatus.NEEDS_HUMAN_REVIEW.value for section in sections)
    status = TicketStatus.NEEDS_HUMAN_REVIEW.value if needs_review else TicketStatus.EN_EVALUACION.value
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        rows = {
            row.department_id: row
            for row in session.exec(select(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket_id))
        }
        for section in sections:
            row = rows[section["department_id"]]
            for name in SECTION_FIELDS:
                setattr(row, name, section[name])
            session.add(row)
        ticket.status = status
        ticket.response_handoff = build_response_handoff(ticket_id, rfp_id, status, handoff, sections, max_iterations)
        ticket.updated_at = utc_now()
        session.add(ticket)
        session.commit()
    return status
