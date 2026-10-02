"""Nodos del agente (una responsabilidad cada uno) y las condiciones de salida que deciden el siguiente.

Fuentes: `lookup_tickets` consulta el gestor de incidencias (tool, datos en vivo), `retrieve` la base de
conocimiento (RAG) y `recall_memory` la memoria aprobada del agente. `generate_answer` llama una sola vez al modelo
con lo que ya trajeron esas fuentes y recibe la respuesta y, si aplica, una propuesta de memoria; ningún nodo usa
`query()`. Un ticket que no se pudo confirmar nunca llega al modelo: se avisa con un texto fijo, para que el agente
no invente su estado.

Guardrails: `input_guard` decide antes que nada si el mensaje se responde, se reconduce (`small_talk_reply`) o se
rechaza con un texto fijo (`guardrail_refusal`), sin tocar la memoria, las tools ni el modelo. `generate_answer` aísla
el contenido externo antes de enviarlo al modelo, y toda respuesta pasa por `output_guard` antes de devolverse.

Memoria: `load_pending_proposal` y `resolve_proposal` cierran la propuesta del turno anterior con una decisión
explícita del usuario antes de responder; `propose_memory` valida la propuesta del modelo y se la pregunta al
usuario dentro de la misma respuesta. Nada se escribe en la memoria sin esa decisión.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.graph import END

from data.pipelines import rag
from data.process.rag import RagServiceError
from services.support_agent.guardrails import events
from services.support_agent.guardrails.events import GuardrailEvent
from services.support_agent.guardrails.input_guard import check_input
from services.support_agent.guardrails.isolation import sanitize_fragment
from services.support_agent.guardrails.output_guard import SMALL_TALK_FALLBACK, check_output
from services.support_agent.memory import policy
from services.support_agent.memory.decision import classify_decision, resolve
from services.support_agent.memory.models import MemoryDraft, MemoryProposal
from services.support_agent.memory.self_evaluation import AgentReply, generate_reply, memory_fragment
from services.support_agent.memory.store import MemoryUnavailableError, get_memory_store
from services.support_agent.routing import plan_route
from services.support_agent.small_talk import brief_reply
from services.support_agent.state import AgentState
from services.support_agent.tools.incidents import Ticket, TicketQuery, get_ticket, ticket_fragment


logger = logging.getLogger("trackflow.agent")

RECEIVE_QUESTION = "receive_question"
REJECT_QUESTION = "reject_question"
INPUT_GUARD = "input_guard"
GUARDRAIL_REFUSAL = "guardrail_refusal"
SMALL_TALK_REPLY = "small_talk_reply"
OUTPUT_GUARD = "output_guard"
LOAD_PENDING_PROPOSAL = "load_pending_proposal"
RESOLVE_PROPOSAL = "resolve_proposal"
RECALL_MEMORY = "recall_memory"
ROUTE_QUESTION = "route_question"
LOOKUP_TICKETS = "lookup_tickets"
RETRIEVE = "retrieve"
GENERATE_ANSWER = "generate_answer"
TICKET_FALLBACK = "ticket_fallback"
NO_INFORMATION = "no_information"
PROPOSE_MEMORY = "propose_memory"

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

PROPOSAL_QUESTION = "¿Quieres que recuerde esto para próximas conversaciones? «{fact}» Responde sí, no o corrígelo."
DECISION_NOTICES = {
    "approved": "Hecho: lo recordaré en próximas conversaciones («{fact}»).",
    "edited": "Hecho: lo recordaré con tu corrección («{fact}»).",
    "rejected": "Entendido: no lo guardo («{fact}»).",
    "discarded": "No he guardado la propuesta anterior («{fact}») porque no quedó clara tu decisión. Si quieres que "
    "lo recuerde, vuelve a decírmelo.",
}
# Acción registrada por el guard de entrada según su decisión (`allow` con aviso = respuesta acotada).
INPUT_ACTIONS = {"block": "block", "redirect": "redirect", "allow": "constrain"}
# Origen del contenido externo para el motivo del evento de aislamiento.
EXTERNAL_ORIGINS = {"incident-manager": "incident_manager", "agent-memory": "agent_memory"}

MEMORY_UNAVAILABLE = (
    "La memoria del agente no está disponible ahora mismo: en esta respuesta no puedo recordar ni guardar nada."
)


def receive_question(state: AgentState) -> AgentState:
    """Normaliza el mensaje de entrada (sin espacios sobrantes)."""
    question = (state.get("question") or "").strip()
    return {"question": question, "message": question}


def reject_question(state: AgentState) -> AgentState:
    """Termina la corrida sin consultar ninguna fuente: no hay pregunta que responder."""
    return {"error": EMPTY_QUESTION_ERROR}


def input_guard(state: AgentState) -> AgentState:
    """Clasifica el mensaje (`guardrails.input_guard`) y registra la activación si no es una consulta de dominio."""
    verdict = check_input(state["message"], state.get("authorized_orders", []))
    recorded = []
    if verdict.failure_type:
        event = GuardrailEvent(
            guardrail="input_guard",
            failure_type=verdict.failure_type,
            action=INPUT_ACTIONS[verdict.decision],
            reason=verdict.category,
        )
        recorded.append(_record(state, event))
    return {"guardrail": verdict.model_dump(), "guardrail_events": recorded}


def guardrail_refusal(state: AgentState) -> AgentState:
    """Rechazo fijo del guard de entrada: no se consulta ninguna fuente ni se llama al modelo."""
    return {"answer": state["guardrail"]["message"]}


def small_talk_reply(state: AgentState) -> AgentState:
    """Respuesta breve sin RAG ni tools; `output_guard` le añade la reconducción hacia TrackFlow."""
    try:
        answer = brief_reply(state["question"])
    except RagServiceError:
        logger.warning("small_talk_reply sin respuesta del modelo: se usa el texto fijo.")
        answer = SMALL_TALK_FALLBACK
    return {"answer": _with_memory_notices(state, answer)}


def output_guard(state: AgentState) -> AgentState:
    """Valida la respuesta antes de devolverla: fuga de instrucciones, datos sensibles y formato."""
    guardrail = state.get("guardrail") or {}
    check = check_output(
        state["answer"],
        mode="small_talk" if guardrail.get("category") == "small_talk" else "answer",
        sections=[str(fragment.get("section", "")) for fragment in _fragments(state)],
        authorized_orders=state.get("authorized_orders", []),
    )
    answer = check.answer
    if guardrail.get("category") == "country_policy_mix":
        answer = f"{guardrail['message']}\n\n{answer}"
    return {"answer": answer, "guardrail_events": [_record(state, event) for event in check.events]}


def load_pending_proposal(state: AgentState) -> AgentState:
    """Propuesta de memoria del usuario que espera respuesta en esta conversación (antes descarta las caducadas)."""
    if not state.get("user_id"):
        return {"pending_proposal": None}
    try:
        pending = get_memory_store().pending_for(state["user_id"], state["conversation_id"], policy.utc_now())
    except MemoryUnavailableError:
        return {"pending_proposal": None, "memory_notices": _notices(state, MEMORY_UNAVAILABLE)}
    return {"pending_proposal": pending.model_dump(mode="json") if pending else None}


def resolve_proposal(state: AgentState) -> AgentState:
    """Clasifica el mensaje frente a la propuesta pendiente, aplica la decisión y la deja registrada."""
    pending = MemoryProposal.model_validate(state["pending_proposal"])
    message = state["message"]
    store = get_memory_store()
    now = policy.utc_now()
    try:
        if not store.take_pending(pending.user_id, pending.proposal_id):
            # Otra petición ya la resolvió: este mensaje se responde como una pregunta normal.
            return {"pending_proposal": None}
        classification = classify_decision(message, pending)
        resolution = resolve(classification, pending, message)
        if resolution.outcome in ("approved", "edited"):
            store.consolidate(pending, resolution.fact or pending.fact, now)
        store.record_decision(
            pending, resolution, classification=classification, message=message, run_id=state["run_id"], at=now
        )
    except MemoryUnavailableError:
        return {"pending_proposal": None, "memory_notices": _notices(state, MEMORY_UNAVAILABLE)}

    update: AgentState = {
        "pending_proposal": None,
        "memory_decision": {
            "proposal_id": pending.proposal_id,
            "outcome": resolution.outcome,
            "reason": resolution.reason,
            "fact": resolution.fact,
        },
    }
    notice = DECISION_NOTICES[resolution.outcome].format(fact=resolution.fact or pending.fact)
    if resolution.follow_up:
        return {**update, "question": resolution.follow_up, "memory_notices": _notices(state, notice)}
    return {**update, "answer": notice}


def recall_memory(state: AgentState) -> AgentState:
    """Entradas de la memoria aprobada relevantes para la pregunta (lectura explícita, como mucho `MAX_RECALLED`)."""
    try:
        entries = get_memory_store().recall(state["question"], policy.utc_now())
    except MemoryUnavailableError:
        return {"memories": [], "memory_notices": _notices(state, MEMORY_UNAVAILABLE)}
    return {"memories": [memory_fragment(entry) for entry in entries]}


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
    """Respuesta y auto-evaluación de memoria, a partir del contexto, los tickets confirmados y la memoria recordada."""
    context, recorded = _isolate(state, _fragments(state))
    reply = generate_reply(state["question"], context)
    notices = _unconfirmed_notices(state)
    answer = "\n".join([*notices, reply.answer]) if notices else reply.answer
    return {
        "answer": _with_memory_notices(state, answer),
        "memory_candidate": _candidate(reply),
        "guardrail_events": recorded,
    }


def ticket_fallback(state: AgentState) -> AgentState:
    """Respuesta honesta sin llamar al modelo: ningún ticket se pudo confirmar y no hay otro contexto."""
    lines = _unconfirmed_notices(state)
    if state["route"]["needs_knowledge"]:
        lines.append(KNOWLEDGE_ALSO_MISSING)
    return {"answer": _with_memory_notices(state, "\n".join([*lines, TICKET_FALLBACK_SOURCE]))}


def no_information(state: AgentState) -> AgentState:
    """Respuesta fija y honesta (nada superó el umbral), más la auto-evaluación de memoria del mensaje.

    Las correcciones que vale la pena recordar no suelen estar en la base de conocimiento, así que el modelo evalúa
    el mensaje igualmente; su texto no se usa, para no responder sin contexto.
    """
    try:
        reply = generate_reply(state["question"], [])
    except RagServiceError:
        logger.warning("no_information sin auto-evaluación de memoria: el modelo no respondió.")
        reply = None
    return {"answer": _with_memory_notices(state, NO_INFORMATION_ANSWER), "memory_candidate": _candidate(reply)}


def propose_memory(state: AgentState) -> AgentState:
    """Valida la propuesta del modelo y, si pasa, la deja pendiente y la pregunta al final de la respuesta."""
    if not state.get("user_id"):
        logger.info("propose_memory sin usuario autenticado: no se propone nada.")
        return {"memory_proposal": None}
    draft = MemoryDraft.model_validate(state["memory_candidate"])
    now = policy.utc_now()
    proposal = policy.build_proposal(
        draft,
        message=state["question"],
        user_id=state["user_id"],
        conversation_id=state["conversation_id"],
        run_id=state["run_id"],
        now=now,
    )
    store = get_memory_store()
    try:
        if isinstance(proposal, list):
            store.record_blocked(
                draft,
                proposal,
                message=state["question"],
                user_id=state["user_id"],
                conversation_id=state["conversation_id"],
                run_id=state["run_id"],
                at=now,
            )
            return {"memory_proposal": None}
        if store.already_remembered(proposal):
            store.record_skipped(proposal, "already_remembered")
            return {"memory_proposal": None}
        # Una sola propuesta pendiente por usuario: si ya tiene otra sin resolver, esta no se lanza.
        if not store.open_pending(proposal):
            store.record_skipped(proposal, "pending_exists")
            return {"memory_proposal": None}
    except MemoryUnavailableError:
        return {"memory_proposal": None, "answer": f"{state['answer']}\n\n{MEMORY_UNAVAILABLE}"}
    return {
        "memory_proposal": proposal.model_dump(mode="json"),
        "answer": f"{state['answer']}\n\n{PROPOSAL_QUESTION.format(fact=proposal.fact)}",
    }


def route_after_question(state: AgentState) -> Literal["reject_question", "input_guard"]:
    return REJECT_QUESTION if not state["question"] else INPUT_GUARD


def route_after_input_guard(state: AgentState) -> Literal["guardrail_refusal", "load_pending_proposal"]:
    return GUARDRAIL_REFUSAL if state["guardrail"]["decision"] == "block" else LOAD_PENDING_PROPOSAL


def route_after_pending(state: AgentState) -> Literal["resolve_proposal", "small_talk_reply", "recall_memory"]:
    # Con una propuesta pendiente, también el small talk ("gracias, sí, guárdalo") pasa por la decisión.
    return RESOLVE_PROPOSAL if state.get("pending_proposal") else _answer_route(state)


def route_after_resolution(state: AgentState) -> Literal["small_talk_reply", "recall_memory", "__end__"]:
    # Si el mensaje solo respondía a la propuesta, la confirmación de la decisión es la respuesta.
    return END if state.get("answer") else _answer_route(state)


def route_after_plan(state: AgentState) -> Literal["lookup_tickets", "retrieve"]:
    return LOOKUP_TICKETS if state["route"]["ticket_ids"] else RETRIEVE


def route_after_lookup(state: AgentState) -> Literal["retrieve", "generate_answer", "ticket_fallback"]:
    if state["route"]["needs_knowledge"]:
        return RETRIEVE
    return GENERATE_ANSWER if _found(state) else TICKET_FALLBACK


def route_after_retrieve(state: AgentState) -> Literal["generate_answer", "ticket_fallback", "no_information"]:
    if state["context"] or _found(state):
        return GENERATE_ANSWER
    if state.get("tickets"):
        return TICKET_FALLBACK
    return GENERATE_ANSWER if state.get("memories") else NO_INFORMATION


def route_after_answer(state: AgentState) -> Literal["propose_memory", "__end__"]:
    return PROPOSE_MEMORY if state.get("memory_candidate") else END


def _answer_route(state: AgentState) -> Literal["small_talk_reply", "recall_memory"]:
    return SMALL_TALK_REPLY if state["guardrail"]["decision"] == "redirect" else RECALL_MEMORY


def _fragments(state: AgentState) -> list[dict[str, Any]]:
    """Todo el contenido externo de la corrida: base de conocimiento, tickets confirmados y memoria recordada."""
    return [
        *state.get("context", []),
        *(ticket_fragment(Ticket.model_validate(lookup["ticket"])) for lookup in _found(state)),
        *state.get("memories", []),
    ]


def _isolate(
    state: AgentState, fragments: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fragmentos sin órdenes incrustadas, y una activación registrada por cada fragmento que hubo que limpiar."""
    clean = []
    recorded = []
    for fragment in fragments:
        sanitized, removed = sanitize_fragment(fragment)
        clean.append(sanitized)
        if removed:
            origin = EXTERNAL_ORIGINS.get(str(fragment.get("source_document")), "knowledge_base")
            event = GuardrailEvent(
                guardrail="external_content_isolation",
                failure_type="security",
                action="sanitize",
                reason=f"embedded_instruction_in_{origin}",
            )
            recorded.append(_record(state, event))
    return clean, recorded


def _record(state: AgentState, event: GuardrailEvent) -> dict[str, Any]:
    return events.record(event, run_id=state.get("run_id"), conversation_id=state.get("conversation_id"))


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


def _notices(state: AgentState, notice: str) -> list[str]:
    notices = list(state.get("memory_notices", []))
    return notices if notice in notices else [*notices, notice]


def _with_memory_notices(state: AgentState, answer: str) -> str:
    return "\n\n".join([*state.get("memory_notices", []), answer])


def _candidate(reply: AgentReply | None) -> dict[str, Any] | None:
    return reply.proposal.model_dump() if reply and reply.proposal else None
