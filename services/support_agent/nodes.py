"""Nodos del agente (una responsabilidad cada uno) y las condiciones de salida que deciden el siguiente.

Fuentes: `lookup_tickets` consulta el gestor de incidencias (tool, datos en vivo) y `retrieve` la base de
conocimiento (RAG). `generate_answer` llama a `generate_answer()` de `data/pipelines/rag.py` con lo que ya trajeron
esas fuentes; ningún nodo usa `query()`. Un ticket que no se pudo confirmar nunca llega al modelo: se avisa con un
texto fijo, para que el agente no invente su estado.
"""

from __future__ import annotations

from typing import Any, Literal

from data.pipelines import rag
from services.support_agent.routing import plan_route
from services.support_agent.state import AgentState
from services.support_agent.tools.incidents import Ticket, TicketQuery, get_ticket, ticket_fragment


RECEIVE_QUESTION = "receive_question"
REJECT_QUESTION = "reject_question"
ROUTE_QUESTION = "route_question"
LOOKUP_TICKETS = "lookup_tickets"
RETRIEVE = "retrieve"
GENERATE_ANSWER = "generate_answer"
TICKET_FALLBACK = "ticket_fallback"
NO_INFORMATION = "no_information"

EMPTY_QUESTION_ERROR = "La pregunta está vacía: escribe qué quiere saber el cliente."

NO_INFORMATION_ANSWER = (
    "No tengo información sobre eso en la base de conocimiento de TrackFlow. Antes de responder al cliente, "
    "confírmalo con el equipo responsable.\nFuente: sin información en la base de conocimiento"
)
TICKET_NOT_FOUND = "No encuentro el ticket {ticket_id} en el gestor de incidencias; revisa el número antes de responder al cliente."
TICKET_UNCONFIRMED = (
    "No pude confirmar el estado del ticket {ticket_id} ahora mismo: el gestor de incidencias no respondió. "
    "Vuelve a intentarlo en unos minutos."
)
KNOWLEDGE_ALSO_MISSING = "Sobre el resto de la pregunta, no tengo información en la base de conocimiento de TrackFlow."
TICKET_FALLBACK_SOURCE = "Fuente: sin confirmación del gestor de incidencias"


def receive_question(state: AgentState) -> AgentState:
    """Normaliza la pregunta de entrada (sin espacios sobrantes)."""
    return {"question": (state.get("question") or "").strip()}


def reject_question(state: AgentState) -> AgentState:
    """Termina la corrida sin consultar ninguna fuente: no hay pregunta que responder."""
    return {"error": EMPTY_QUESTION_ERROR}


def route_question(state: AgentState) -> AgentState:
    """Decide qué fuentes necesita la pregunta: tickets, base de conocimiento o ambas."""
    return {"route": plan_route(state["question"]).model_dump()}


def lookup_tickets(state: AgentState) -> AgentState:
    """Consulta en vivo cada ticket de la pregunta con la tool de solo lectura del gestor de incidencias."""
    return {
        "tickets": [
            get_ticket(TicketQuery(ticket_id=ticket_id)).model_dump(mode="json")
            for ticket_id in state["route"]["ticket_ids"]
        ]
    }


def retrieve(state: AgentState) -> AgentState:
    """Payloads de la base de conocimiento por encima de `min_score` (`data.pipelines.rag.retrieve`)."""
    return {"context": rag.retrieve(state["question"])}


def generate_answer(state: AgentState) -> AgentState:
    """Respuesta del modelo a partir del contexto recuperado y de los tickets confirmados."""
    context = list(state.get("context", [])) + [
        ticket_fragment(Ticket.model_validate(lookup["ticket"])) for lookup in _found(state)
    ]
    answer = rag.generate_answer(state["question"], context)
    notices = _unconfirmed_notices(state)
    return {"answer": "\n".join([*notices, answer]) if notices else answer}


def ticket_fallback(state: AgentState) -> AgentState:
    """Respuesta honesta sin llamar al modelo: ningún ticket se pudo confirmar y no hay otro contexto."""
    lines = _unconfirmed_notices(state)
    if state["route"]["needs_knowledge"]:
        lines.append(KNOWLEDGE_ALSO_MISSING)
    return {"answer": "\n".join([*lines, TICKET_FALLBACK_SOURCE])}


def no_information(state: AgentState) -> AgentState:
    """Respuesta honesta sin llamar al modelo: ningún fragmento superó el umbral."""
    return {"answer": NO_INFORMATION_ANSWER}


def route_after_question(state: AgentState) -> Literal["reject_question", "route_question"]:
    return REJECT_QUESTION if not state["question"] else ROUTE_QUESTION


def route_after_plan(state: AgentState) -> Literal["lookup_tickets", "retrieve"]:
    return LOOKUP_TICKETS if state["route"]["ticket_ids"] else RETRIEVE


def route_after_lookup(state: AgentState) -> Literal["retrieve", "generate_answer", "ticket_fallback"]:
    if state["route"]["needs_knowledge"]:
        return RETRIEVE
    return GENERATE_ANSWER if _found(state) else TICKET_FALLBACK


def route_after_retrieve(state: AgentState) -> Literal["generate_answer", "ticket_fallback", "no_information"]:
    if state["context"] or _found(state):
        return GENERATE_ANSWER
    return TICKET_FALLBACK if state.get("tickets") else NO_INFORMATION


def _found(state: AgentState) -> list[dict[str, Any]]:
    return [lookup for lookup in state.get("tickets", []) if lookup["outcome"] == "found"]


def _unconfirmed_notices(state: AgentState) -> list[str]:
    return [
        (TICKET_NOT_FOUND if lookup["outcome"] == "not_found" else TICKET_UNCONFIRMED).format(
            ticket_id=lookup["ticket_id"]
        )
        for lookup in state.get("tickets", [])
        if lookup["outcome"] != "found"
    ]
