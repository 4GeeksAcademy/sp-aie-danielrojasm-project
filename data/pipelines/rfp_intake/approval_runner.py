"""Ciclo de vida de la Parte 3 sobre el mismo ticket: del handoff de la Parte 2 al documento final.

Dos puntos de entrada explícitos, ambos bajo `checkpoints.ticket_lock`:

- `start_approval` (tarea `rfp_intake.start_approval`, que encola la Parte 2 al terminar): solo para tickets en
  `en_evaluación` o `needs_human_review` con `response_handoff` (`rfp_intake.response_handoff.v1`). Construye el
  estado inicial con los borradores y `EvaluationResult` de la Parte 2 y ejecuta el grafo hasta que todas las ramas
  quedan esperando a su responsable. El ticket pasa a `esperando_aprobación` en cuanto se abre la primera revisión.
- `submit_decision` (tarea `rfp_intake.resume_approval`, que encola la API): valida la decisión contra la revisión
  que está pendiente de verdad en el checkpoint y reanuda **solo esa interrupción** con
  `Command(resume={interrupt_id: decisión})`. No reinicia nada: el resto de ramas siguen esperando.

Cuando todas las secciones están aprobadas, el grafo genera el documento final, lo guarda en `rfp_final_documents`
y deja el ticket en `terminado`. Un fallo (gateway, base de datos) deja `last_error` en el ticket, que no cambia de
estado; el siguiente intento continúa desde el último checkpoint (`graph.invoke(None)`), sin repetir lo terminado.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from data.pipelines.rfp_intake import approval, approval_graph, checkpoints, response_runner
from data.pipelines.rfp_intake.departments import TicketStatus
from data.pipelines.rfp_intake.runner import TicketNotFoundError, record_failure
from data.pipelines.rfp_intake.schema import (
    RfpDepartmentSection,
    RfpFinalDocument,
    RfpMetadata,
    RfpTicket,
    ensure_response_schema,
    utc_now,
)


logger = logging.getLogger("trackflow.rfp_intake")

ENTRY_STATUSES = frozenset({TicketStatus.EN_EVALUACION.value, TicketStatus.NEEDS_HUMAN_REVIEW.value})
# Cada ronda de arbitraje y de revisión son pocos pasos; el límite real lo ponen `max_rounds` y `max_iterations`.
RECURSION_LIMIT = 200
SECTION_FIELDS = frozenset(
    {
        "draft_status",
        "iterations",
        "draft_content",
        "evaluation_results",
        "evaluation_history",
        "approval_status",
        "approver",
        "approved_at",
        "review_round",
        "revisions",
        "approval_history",
    }
)

_graphs: dict[str, CompiledStateGraph] = {}
_graphs_lock = threading.Lock()


class NoPendingReviewError(LookupError):
    """El departamento no tiene una revisión esperando decisión (ya decidida, o el ticket no está en la Parte 3)."""


class CheckpointUnavailableError(RuntimeError):
    """No se pudo leer el checkpoint del ticket."""


class DatabaseApprovalSink:
    """Escribe en PostgreSQL lo que el grafo de aprobación decide, en cuanto lo decide.

    Las ramas de departamento corren en hilos distintos: el lock serializa las escrituras de este proceso.
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
            self._touch(session)
            session.commit()

    def ticket_status(self, status: str) -> None:
        with self._lock, Session(self.engine) as session:
            ticket = self._touch(session)
            if ticket.status != status:
                logger.info("ticket=%s status=%s", self.ticket_id, status)
                ticket.status = status
            session.commit()

    def arbitration(self, record: dict[str, Any]) -> None:
        with self._lock, Session(self.engine) as session:
            ticket = self._touch(session)
            ticket.arbitrations = [*ticket.arbitrations, record]
            session.commit()

    def trace(self, entry: dict[str, Any]) -> None:
        with self._lock, Session(self.engine) as session:
            ticket = self._touch(session)
            ticket.trace = [*ticket.trace, entry]
            session.commit()

    def final_document(self, document: dict[str, Any]) -> None:
        """Guarda el documento y cierra el ticket en `terminado` en la misma transacción."""
        with self._lock, Session(self.engine) as session:
            existing = session.exec(
                select(RfpFinalDocument).where(RfpFinalDocument.ticket_id == self.ticket_id)
            ).first()
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(
                RfpFinalDocument(
                    ticket_id=self.ticket_id,
                    rfp_id=document["rfp_id"],
                    currency=document["currency"],
                    sections=document["sections"],
                    content=document["content"],
                    generated_at=datetime.fromisoformat(document["generated_at"]),
                )
            )
            ticket = self._touch(session)
            ticket.status = TicketStatus.TERMINADO.value
            session.commit()
        logger.info("ticket=%s status=%s documento final guardado.", self.ticket_id, TicketStatus.TERMINADO.value)

    def _touch(self, session: Session) -> RfpTicket:
        ticket = session.get(RfpTicket, self.ticket_id)
        if ticket is None:
            raise TicketNotFoundError(self.ticket_id)
        ticket.updated_at = utc_now()
        session.add(ticket)
        return ticket


def approval_graph_for(engine: Engine) -> CompiledStateGraph:
    """Grafo de aprobación compilado con el checkpointer de la base del engine (uno por base y proceso)."""
    key = engine.url.render_as_string(hide_password=True)
    with _graphs_lock:
        if key not in _graphs:
            _graphs[key] = approval_graph.define_graph().compile(checkpointer=checkpoints.checkpointer_for(engine))
        return _graphs[key]


def run_config(engine: Engine, ticket_id: str) -> dict[str, Any]:
    sink = DatabaseApprovalSink(engine, ticket_id)
    return {
        "configurable": {
            "thread_id": checkpoints.thread_id_for(ticket_id),
            "approval_sink": sink,
            "trace_sink": sink,
            # El ciclo generador-evaluador de la Parte 2 informa del progreso de una revisión por aquí.
            "progress": sink,
        },
        "recursion_limit": RECURSION_LIMIT,
    }


def start_approval(engine: Engine, ticket_id: str, max_rounds: int | None = None) -> str:
    """Abre la aprobación por departamento de un ticket que terminó la Parte 2 y devuelve su estado."""
    ensure_response_schema(engine)
    rounds = max_rounds or approval_graph.max_rounds_from_env()
    graph = approval_graph_for(engine)
    with checkpoints.ticket_lock(engine, ticket_id):
        config = run_config(engine, ticket_id)
        snapshot = graph.get_state(config)
        if snapshot.values:
            # Ya empezó: si un intento anterior se quedó a mitad, se continúa desde el último checkpoint.
            if _unfinished_tasks(snapshot):
                logger.warning("ticket=%s la Parte 3 se quedó a mitad: continúa desde su checkpoint.", ticket_id)
                _run(engine, ticket_id, graph, None, config)
            else:
                logger.info("ticket=%s la Parte 3 ya está en curso o terminada: no se vuelve a empezar.", ticket_id)
            return ticket_status(engine, ticket_id)
        with Session(engine) as session:
            ticket = session.get(RfpTicket, ticket_id)
            if ticket is None:
                raise TicketNotFoundError(ticket_id)
            if ticket.response_handoff is None or ticket.status not in ENTRY_STATUSES:
                logger.info("ticket=%s en %s: la Parte 3 no lo procesa.", ticket_id, ticket.status)
                return ticket.status
            initial = initial_state(session, ticket, rounds)
            ticket.approval_attempts += 1
            ticket.last_error = None
            ticket.updated_at = utc_now()
            session.add(ticket)
            session.commit()
        logger.info(
            "ticket=%s inicio de la Parte 3 departments=%s max_rounds=%s thread_id=%s",
            ticket_id,
            list(initial["sections"]),
            rounds,
            config["configurable"]["thread_id"],
        )
        _run(engine, ticket_id, graph, initial, config)
    return ticket_status(engine, ticket_id)


def submit_decision(engine: Engine, ticket_id: str, department_id: str, raw: dict[str, Any]) -> str:
    """Valida la decisión del responsable y reanuda solo la rama de su departamento."""
    decision = approval.ApprovalDecision.model_validate(raw)
    graph = approval_graph_for(engine)
    with checkpoints.ticket_lock(engine, ticket_id):
        config = run_config(engine, ticket_id)
        if _unfinished_tasks(graph.get_state(config)):
            _run(engine, ticket_id, graph, None, config)
        review = _pending(graph, config).get(department_id)
        if review is None:
            raise NoPendingReviewError(f"La sección {department_id} no tiene ninguna revisión esperando decisión.")
        approval.check_against(decision, review)
        logger.info(
            "ticket=%s resume department=%s decision=%s review_round=%s interrupt_id=%s",
            ticket_id,
            department_id,
            decision.decision,
            decision.review_round,
            review["interrupt_id"],
        )
        _run(engine, ticket_id, graph, Command(resume={review["interrupt_id"]: decision.model_dump()}), config)
    return ticket_status(engine, ticket_id)


def pending_reviews(engine: Engine, ticket_id: str) -> dict[str, dict[str, Any]]:
    """Revisiones esperando decisión, por departamento: el `ReviewRequest` del `interrupt` más su `interrupt_id`."""
    try:
        graph = approval_graph_for(engine)
        return _pending(graph, run_config(engine, ticket_id))
    except Exception as error:
        logger.error("ticket=%s no se pudo leer el checkpoint: %s", ticket_id, type(error).__name__, exc_info=error)
        raise CheckpointUnavailableError(ticket_id) from error


def forget(engine: Engine, ticket_id: str) -> None:
    """Borra el hilo de checkpoints del ticket (reproceso completo desde la Parte 1)."""
    checkpoints.checkpointer_for(engine).delete_thread(checkpoints.thread_id_for(ticket_id))


def ticket_status(engine: Engine, ticket_id: str) -> str:
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        return ticket.status


def initial_state(session: Session, ticket: RfpTicket, max_rounds: int) -> dict[str, Any]:
    """Estado inicial a partir del handoff de la Parte 2; los datos compartidos salen del handoff de la Parte 1."""
    response = ticket.response_handoff or {}
    version = response_runner.RESPONSE_HANDOFF_VERSION
    if response.get("version") != version:
        raise response_runner.HandoffError(f"El ticket {ticket.ticket_id} no tiene un handoff {version} de la Parte 2.")
    handoff = response_runner.read_handoff(ticket)
    metadata = session.exec(select(RfpMetadata).where(RfpMetadata.ticket_id == ticket.ticket_id)).first()
    rows = {
        row.department_id: row
        for row in session.exec(select(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket.ticket_id))
    }
    sections = {
        item["department_id"]: {
            "department_id": item["department_id"],
            "draft_content": item["draft_content"],
            "draft_status": item["draft_status"],
            "iterations": item["iterations"],
            "evaluation_result": item["evaluation_result"],
            "evaluation_history": rows[item["department_id"]].evaluation_history,
            "approval_status": None,
            "approver": None,
            "approved_at": None,
            "review_round": 0,
            "revisions": 0,
            "decisions": [],
            "arbitration_notes": [],
            "instruction": None,
            "committed_monthly_capacity": None,
        }
        for item in response["sections"]
    }
    return {
        "ticket_id": ticket.ticket_id,
        "rfp_id": ticket.rfp_id,
        "shared": response_runner.shared_brief(handoff, metadata),
        "workstreams": {workstream["department_id"]: workstream for workstream in handoff["workstreams"]},
        "max_rounds": max_rounds,
        "max_iterations": response["max_iterations"],
        "sections": sections,
        "arbitration_round": 0,
        "arbitrations": [],
        "trace": [],
    }


def _run(engine: Engine, ticket_id: str, graph: CompiledStateGraph, payload: Any, config: dict[str, Any]) -> None:
    try:
        graph.invoke(payload, config)
    except Exception as error:
        record_failure(engine, ticket_id, error)
        raise
    with Session(engine) as session:
        ticket = session.get(RfpTicket, ticket_id)
        if ticket is not None and ticket.last_error is not None:
            # Un intento anterior falló y este ha continuado desde el checkpoint: el error ya no aplica.
            ticket.last_error = None
            session.add(ticket)
            session.commit()


def _pending(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    # Una rama ya reanudada conserva su interrupción antigua en el snapshot, pero tiene resultado: no está pendiente.
    pending = {}
    for task in graph.get_state(config).tasks:
        if task.result is not None:
            continue
        for item in task.interrupts:
            value = item.value
            if isinstance(value, dict) and value.get("kind") == "department_approval":
                pending[value["department_id"]] = {**value, "interrupt_id": item.id}
    return pending


def _unfinished_tasks(snapshot: Any) -> bool:
    # Una tarea sin resultado ni interrupción falló (o su proceso murió) a mitad: hay que continuarla.
    return any(task.result is None and not task.interrupts for task in snapshot.tasks)
