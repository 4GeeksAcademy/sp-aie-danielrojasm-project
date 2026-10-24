"""Ciclo de vida del ticket de una RFP: recepción, ejecución del grafo y persistencia en PostgreSQL.

- `receive_upload` (lo llama la API): guarda el PDF en `data/raw/rfp_intake/<ticket_id>.pdf` y crea el ticket en
  `analizando`. No ejecuta el grafo.
- `process_ticket` (lo llama el worker de Celery o `scripts/rfp_intake.py`): ejecuta el grafo y guarda el
  resultado en una sola transacción: `descartado` con el motivo del clasificador, o `analisis_completo` con
  metadatos, secciones por departamento, síntesis y handoff.
- En cuanto el grafo confirma que el documento es una RFP válida (metadatos extraídos, ticket aún en
  `analizando`), se reserva su `rfp_id` en el ticket y se llama a `on_rfp_detected`: el worker lo usa para la
  notificación en tiempo real (`services/rfp_intake/events.py`). Un fallo de ese aviso nunca rompe el análisis.

El ticket siempre dice la verdad: mientras el grafo corre está en `analizando`; si falla, sigue en `analizando` con
`last_error` y `attempts` (la tarea se reintenta y la UI lo muestra) y no queda nada a medio escribir. Solo se
procesan tickets en `analizando`, así que un mensaje entregado dos veces no repite el trabajo.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from data.pipelines.rfp_intake import graph as intake_graph
from data.pipelines.rfp_intake import tracing
from data.pipelines.rfp_intake.departments import TicketStatus
from data.pipelines.rfp_intake.schema import (
    RfpDepartmentSection,
    RfpFinalDocument,
    RfpMetadata,
    RfpTicket,
    ensure_response_schema,
    new_id,
    utc_now,
)
from data.pipelines.rfp_intake.synthesizer import build_handoff


logger = logging.getLogger("trackflow.rfp_intake")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = "data/raw/rfp_intake"


class DatabaseNotConfiguredError(RuntimeError):
    """Falta `DATABASE_URL`: los tickets de RFP viven en PostgreSQL (Supabase)."""


class TicketNotFoundError(LookupError):
    pass


# Recibe el ticket (en `analizando`, con su `rfp_id` ya reservado) y los metadatos extraídos.
RfpDetectedCallback = Callable[[RfpTicket, dict[str, Any]], None]


@dataclass(frozen=True)
class TicketDetail:
    ticket: RfpTicket
    metadata: RfpMetadata | None
    sections: list[RfpDepartmentSection]
    final_document: RfpFinalDocument | None = None


@lru_cache(maxsize=4)
def _engine_for(database_url: str) -> Engine:
    # pool_pre_ping descarta conexiones que el pooler de Supabase haya cerrado.
    return create_engine(database_url, pool_pre_ping=True)


def intake_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise DatabaseNotConfiguredError("Falta DATABASE_URL: los tickets de RFP viven en PostgreSQL (Supabase).")
    engine = _engine_for(database_url)
    ensure_response_schema(engine)
    return engine


# --- Recepción ---------------------------------------------------------------------------------


def raw_dir() -> Path:
    configured = Path(os.getenv("RFP_RAW_DIR", DEFAULT_RAW_DIR))
    return configured if configured.is_absolute() else REPO_ROOT / configured


def resolve_pdf_path(raw_pdf_path: str) -> Path:
    path = Path(raw_pdf_path)
    return path if path.is_absolute() else REPO_ROOT / path


def receive_upload(engine: Engine, *, content: bytes, filename: str, uploaded_by: str) -> RfpTicket:
    ticket_id = new_id()
    target = raw_dir() / f"{ticket_id}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    # Ruta relativa a la raíz del monorepo: la API y el worker montan `data/` en el mismo sitio.
    stored_path = target.relative_to(REPO_ROOT).as_posix() if target.is_relative_to(REPO_ROOT) else str(target)
    ticket = RfpTicket(
        ticket_id=ticket_id, original_filename=filename, raw_pdf_path=stored_path, uploaded_by=uploaded_by
    )
    try:
        with Session(engine) as session:
            session.add(ticket)
            session.commit()
            session.refresh(ticket)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    logger.info("ticket=%s recibido file=%r path=%s bytes=%s", ticket_id, filename, stored_path, len(content))
    return ticket


def cancel_upload(engine: Engine, ticket_id: str) -> None:
    """Deshace una recepción que no se pudo encolar: sin tarea, el ticket se quedaría en `analizando` para siempre."""
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            return
        resolve_pdf_path(ticket.raw_pdf_path).unlink(missing_ok=True)
        session.delete(ticket)
        session.commit()
    logger.warning("ticket=%s recepción cancelada: no se pudo encolar el análisis.", ticket_id)


# --- Consultas ---------------------------------------------------------------------------------


def list_tickets(engine: Engine, limit: int = 50) -> list[tuple[RfpTicket, RfpMetadata | None]]:
    with Session(engine) as session:
        rows = session.exec(
            select(RfpTicket, RfpMetadata)
            .join(RfpMetadata, col(RfpMetadata.ticket_id) == col(RfpTicket.ticket_id), isouter=True)
            .order_by(col(RfpTicket.created_at).desc())
            .limit(limit)
        ).all()
        return [(ticket, metadata) for ticket, metadata in rows]


def get_ticket_detail(engine: Engine, ticket_id: str) -> TicketDetail:
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        metadata = session.exec(select(RfpMetadata).where(RfpMetadata.ticket_id == ticket_id)).first()
        sections = session.exec(
            select(RfpDepartmentSection)
            .where(RfpDepartmentSection.ticket_id == ticket_id)
            .order_by(col(RfpDepartmentSection.id))
        ).all()
        document = session.exec(select(RfpFinalDocument).where(RfpFinalDocument.ticket_id == ticket_id)).first()
        return TicketDetail(ticket, metadata, list(sections), document)


# --- Procesamiento -----------------------------------------------------------------------------


def process_ticket(engine: Engine, ticket_id: str, on_rfp_detected: RfpDetectedCallback | None = None) -> str:
    """Ejecuta el grafo para un ticket en `analizando` y devuelve su estado final."""
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        if ticket.status != TicketStatus.ANALIZANDO.value:
            logger.info("ticket=%s ya está en %s: no se vuelve a procesar.", ticket_id, ticket.status)
            return ticket.status
        ticket.attempts += 1
        ticket.last_error = None
        ticket.updated_at = utc_now()
        session.add(ticket)
        session.commit()
        attempt, pdf_path = ticket.attempts, resolve_pdf_path(ticket.raw_pdf_path)

    logger.info("ticket=%s attempt=%s inicio del grafo rfp_intake.", ticket_id, attempt)
    try:
        state = intake_graph.run_graph(
            ticket_id,
            str(pdf_path),
            on_metadata=(lambda metadata: _rfp_detected(engine, ticket_id, metadata, on_rfp_detected))
            if on_rfp_detected
            else None,
        )
        status = _persist_result(engine, ticket_id, state)
    except Exception as error:
        record_failure(engine, ticket_id, error)
        raise
    logger.info("ticket=%s attempt=%s status=%s", ticket_id, attempt, status)
    return status


def _rfp_detected(
    engine: Engine, ticket_id: str, metadata: dict[str, Any], on_rfp_detected: RfpDetectedCallback
) -> None:
    """Reserva el `rfp_id` (el mismo en un reintento) y avisa. El ticket sigue en `analizando`."""
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        if ticket.rfp_id is None:
            ticket.rfp_id = new_id()
            ticket.updated_at = utc_now()
            session.add(ticket)
            session.commit()
            session.refresh(ticket)
    try:
        on_rfp_detected(ticket, metadata)
    except Exception:
        logger.exception("ticket=%s rfp_id=%s no se pudo notificar la RFP nueva.", ticket_id, ticket.rfp_id)


def record_failure(engine: Engine, ticket_id: str, error: BaseException) -> None:
    message = describe_error(error)
    logger.error("ticket=%s el análisis falló: %s", ticket_id, message, exc_info=error)
    try:
        with Session(engine) as session:
            ticket = session.get(RfpTicket, ticket_id)
            if ticket is None:
                return
            ticket.last_error = message
            ticket.updated_at = utc_now()
            session.add(ticket)
            session.commit()
    except Exception:
        logger.exception("ticket=%s no se pudo registrar el fallo en la base de datos.", ticket_id)


def reset_ticket(engine: Engine, ticket_id: str) -> None:
    """Vuelve a dejar un ticket en `analizando` sin resultados de ninguna parte (reproceso manual desde `scripts/`).

    No borra el hilo de checkpoints de la Parte 3: lo hace `approval_runner.forget` (el script llama a los dos).
    """
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        _delete_results(session, ticket_id)
        session.exec(delete(RfpFinalDocument).where(col(RfpFinalDocument.ticket_id) == ticket_id))
        ticket.status = TicketStatus.ANALIZANDO.value
        ticket.rfp_id = None
        ticket.is_rfp = ticket.classification_confidence = ticket.classification_reason = None
        ticket.synthesis = ticket.handoff = ticket.response_handoff = None
        ticket.trace, ticket.arbitrations = [], []
        ticket.last_error = None
        ticket.updated_at = utc_now()
        session.add(ticket)
        session.commit()


def describe_error(error: BaseException) -> str:
    """Clase y primera línea del error: sin trazas, URLs ni datos de conexión."""
    first_line = (str(error).strip().splitlines() or [""])[0][:300]
    return f"{type(error).__name__}: {first_line}" if first_line else type(error).__name__


def _delete_results(session: Session, ticket_id: str) -> None:
    session.exec(delete(RfpDepartmentSection).where(col(RfpDepartmentSection.ticket_id) == ticket_id))
    session.exec(delete(RfpMetadata).where(col(RfpMetadata.ticket_id) == ticket_id))


def _persist_result(engine: Engine, ticket_id: str, state: dict[str, Any]) -> str:
    classification = state["classification"]
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        ticket.is_rfp = classification["is_rfp"]
        ticket.classification_confidence = classification["confidence"]
        ticket.classification_reason = classification["reason"]
        ticket.trace = tracing.ordered(state.get("trace", []))
        ticket.updated_at = utc_now()
        _delete_results(session, ticket_id)
        if not classification["is_rfp"]:
            ticket.status = TicketStatus.DESCARTADO.value
            session.add(ticket)
            session.commit()
            return ticket.status

        metadata, readability, synthesis = state["metadata"], state["readability"], state["synthesis"]
        departments = [workstream["department_id"] for workstream in synthesis["workstreams"]]
        record = RfpMetadata(
            # Si ya se notificó la RFP, el `rfp_id` anunciado es el que se guarda.
            rfp_id=ticket.rfp_id or new_id(),
            ticket_id=ticket_id,
            client_name=metadata["client_name"],
            client_country=metadata["client_country"],
            currency=metadata["currency"],
            client_reference=metadata["client_reference"],
            services_requested=metadata["services_requested"],
            monthly_volume=metadata["monthly_volume"],
            deadline=date.fromisoformat(metadata["deadline"]) if metadata["deadline"] else None,
            budget_range=metadata["budget_range"],
            departments_needed=departments,
            document_markdown=state["markdown"],
            **readability,
        )
        session.add(record)
        for section in state.get("sections", []):
            session.add(
                RfpDepartmentSection(
                    ticket_id=ticket_id,
                    department_id=section["department_id"],
                    responsible=section["responsible"],
                    key_aspects=section["key_aspects"],
                    requested_inputs=section["requested_inputs"],
                    open_questions=section["open_questions"],
                )
            )
        ticket.rfp_id = record.rfp_id
        ticket.synthesis = synthesis
        ticket.handoff = build_handoff(ticket_id, record.rfp_id, metadata, synthesis)
        ticket.status = TicketStatus.ANALISIS_COMPLETO.value
        session.add(ticket)
        session.commit()
        return ticket.status
