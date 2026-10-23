"""Memoria del agente: qué se puede recordar, decisión explícita del usuario, auditoría y consolidación.

Sin servicios reales: Redis es el `fakeredis` de `tests/conftest.py`; el RAG, el enrutador, la generación con
auto-evaluación (`generate_reply`) y el clasificador de decisiones (`classify_decision`) son dobles.
"""

from datetime import datetime, timedelta, timezone

import fakeredis
import openai
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from data.pipelines import rag
from data.process.rag import RagServiceError
from services.support_agent import nodes, prompt
from services.support_agent.graph import compile_graph, define_graph
from services.support_agent.memory import decision, policy, self_evaluation
from services.support_agent.memory.models import DecisionClassification, MemoryDraft, MemoryProposal
from services.support_agent.memory.self_evaluation import AgentReply, parse_reply
from services.support_agent.memory.store import MemoryStore, MemoryUnavailableError, get_memory_store, use_memory_store
from services.support_agent.routing import RoutePlan
from services.support_agent.runner import run_agent
from services.support_agent.tracing import executed_nodes, load_trace


NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
USER = "user-cx-1"
SEUR_MESSAGE = (
    "En realidad SEUR ya no cubre esa zona rural de Zaragoza, hay que usar el carrier local desde el mes pasado."
)
SEUR_DRAFT = MemoryDraft(
    categoria="carrier_rule",
    hecho="SEUR ya no cubre la zona rural de Zaragoza; hay que usar el transportista local.",
    motivo="Corrige la cobertura de SEUR en la base de conocimiento.",
    cita_usuario="SEUR ya no cubre esa zona rural de Zaragoza",
    transportista="SEUR",
    pais="ES",
)
STRIKE_MESSAGE = (
    "Esos retrasos reportados en incidencias de Los Ángeles esta semana son por la huelga portuaria, no por un "
    "problema nuestro — ya van tres tickets sobre lo mismo."
)
STRIKE_DRAFT = MemoryDraft(
    categoria="incident_context",
    hecho="Los retrasos de Los Ángeles de esta semana se deben a la huelga portuaria, no a TrackFlow.",
    motivo="Evita volver a escalar la misma alerta.",
    cita_usuario="retrasos reportados en incidencias de Los Ángeles esta semana son por la huelga portuaria",
    zona="Los Ángeles",
    pais="US",
)
COSMETICS_MESSAGE = (
    "El cliente de cosméticos siempre quiere su reporte mensual con el desglose de devoluciones primero, antes que "
    "el volumen de envíos."
)
COSMETICS_DRAFT = MemoryDraft(
    categoria="client_preference",
    hecho="El cliente de cosméticos quiere el reporte mensual con el desglose de devoluciones antes que el volumen.",
    motivo="Preferencia recurrente del reporte mensual.",
    cita_usuario="siempre quiere su reporte mensual con el desglose de devoluciones primero",
    cliente="Cliente de cosméticos",
)
CHUNK = {"source_document": "carrier-coverage", "section": "Cobertura", "chunk_index": 1, "text": "SEUR rural."}


def proposal_for(draft: MemoryDraft, message: str, *, user_id: str = USER, conversation_id: str = "conv-1",
                 now: datetime = NOW) -> MemoryProposal:
    proposal = policy.build_proposal(
        draft, message=message, user_id=user_id, conversation_id=conversation_id, run_id="run-0", now=now
    )
    assert isinstance(proposal, MemoryProposal), proposal
    return proposal


def classified(label: str, confidence: float = 0.95, follow_up: str = "", edited: str | None = None):
    return DecisionClassification(decision=label, confianza=confidence, resto_del_mensaje=follow_up,
                                  hecho_editado=edited)


@pytest.fixture
def store() -> MemoryStore:
    return get_memory_store()


@pytest.fixture
def compiled():
    return compile_graph(define_graph(), checkpointer=InMemorySaver())


@pytest.fixture
def agent(monkeypatch):
    """RAG con un fragmento, enrutado al RAG, reloj fijo; `agent.replies` decide qué devuelve el modelo por mensaje."""
    state = {"replies": {}, "decisions": {}, "generated": []}

    def generate_reply(question, context):
        state["generated"].append((question, context))
        return state["replies"].get(question, AgentReply(answer=f"Respuesta a: {question}\nFuente: Cobertura"))

    def classify_decision(message, proposal):
        return state["decisions"][message]

    monkeypatch.setattr(rag, "retrieve", lambda question: [CHUNK])
    monkeypatch.setattr(nodes, "plan_route", lambda question: RoutePlan(needs_knowledge=True, decided_by="llm"))
    monkeypatch.setattr(nodes, "generate_reply", generate_reply)
    monkeypatch.setattr(nodes, "classify_decision", classify_decision)
    monkeypatch.setattr(policy, "utc_now", lambda: state.get("now", NOW))
    return state


def turn(compiled, message, *, conversation_id="conv-1", user_id=USER):
    return run_agent(message, conversation_id=conversation_id, user_id=user_id, compiled=compiled)


def events(store: MemoryStore) -> list[tuple[str, str | None]]:
    return [(event["event"], event.get("outcome")) for event in store.audit_log()]


# --- Qué se puede recordar y qué nunca -------------------------------------------------------------


@pytest.mark.parametrize(
    ("draft", "message", "subject_key"),
    [
        (SEUR_DRAFT, SEUR_MESSAGE, "carrier_rule:seur:ES"),
        (STRIKE_DRAFT, STRIKE_MESSAGE, "incident_context:US:los-angeles"),
        (COSMETICS_DRAFT, COSMETICS_MESSAGE, "client_preference:cliente-de-cosmeticos"),
    ],
    ids=["carrier-rule", "recurring-incident", "b2b-report-preference"],
)
def test_the_three_memorable_kinds_become_proposals_keyed_by_subject(draft, message, subject_key):
    proposal = proposal_for(draft, message)

    assert proposal.subject_key == subject_key
    assert proposal.expires_at == NOW + policy.PENDING_TTL
    assert proposal.source_message == policy.redact(message)


@pytest.mark.parametrize(
    ("fact", "message", "violation"),
    [
        ("El destinatario vive en Calle Mayor 12, 3º izquierda.", "Recuerda que vive en Calle Mayor 12, 3º izquierda.",
         "customer_location"),
        ("El cliente final recibe en 742 Evergreen Terrace.", "El cliente final recibe en 742 Evergreen Terrace.",
         "customer_location"),
        ("La marca de cosméticos recoge en su nave del código postal 50197.",
         "La marca de cosméticos recoge en su nave del código postal 50197.", "customer_location"),
        ("La entrega es en 41.6488, -0.8891.", "La entrega es en 41.6488, -0.8891.", "customer_location"),
        ("Los paquetes de SEUR salen por el muelle 4 y el pasillo B.",
         "Los paquetes de SEUR salen por el muelle 4 y el pasillo B.", "warehouse_internal"),
        ("El paquete SH-2024-8821 de SEUR llegó roto.", "El paquete SH-2024-8821 de SEUR llegó roto.", "single_parcel"),
        ("SEUR perdió el envío del ticket 482.", "SEUR perdió el envío del ticket 482.", "single_parcel"),
        ("Estamos negociando con SEUR un descuento del 8 % en la renovación del contrato.",
         "Estamos negociando con SEUR un descuento del 8 % en la renovación del contrato.", "commercial_contract"),
    ],
    ids=["b2c-address", "b2c-us-address", "b2b-postal-code", "coordinates", "warehouse-route", "tracking", "ticket",
         "contract"],
)
def test_what_must_never_be_remembered_is_blocked_whatever_the_model_says(fact, message, violation):
    draft = SEUR_DRAFT.model_copy(update={"fact": fact, "user_quote": message})

    result = policy.build_proposal(draft, message=message, user_id=USER, conversation_id="c", run_id="r", now=NOW)

    assert isinstance(result, list) and violation in result
    assert violation in policy.check_edited_fact(fact)


@pytest.mark.parametrize(
    ("update", "violation"),
    [
        ({"user_quote": "SEUR dejó de operar en Teruel"}, "not_stated_by_user"),
        ({"category": "pricing_rule"}, "category_not_allowed"),
        ({"carrier": "Correos"}, "unknown_carrier"),
        ({"carrier": "UPS"}, "carrier_country_mismatch"),
        ({"fact": "SEUR " * 80}, "fact_too_long"),
    ],
)
def test_proposals_outside_the_allowed_scope_are_rejected(update, violation):
    result = policy.build_proposal(
        SEUR_DRAFT.model_copy(update=update), message=SEUR_MESSAGE, user_id=USER, conversation_id="c", run_id="r",
        now=NOW,
    )

    assert isinstance(result, list) and violation in result


def test_redact_removes_locations_before_anything_reaches_the_audit_log():
    redacted = policy.redact("Entrega en Calle Mayor 12, 50001 Zaragoza, paquete SH-2024-8821.")

    assert "mayor 12" not in redacted and "50001" not in redacted and "8821" not in redacted
    assert "[redactado]" in redacted


# --- Salida estructurada de la generación ------------------------------------------------------------


def test_reply_without_anything_to_remember():
    reply = parse_reply('{"respuesta": "Son 30 días.\\nFuente: Ventana", "propuesta_memoria": null}')

    assert reply == AgentReply(answer="Son 30 días.\nFuente: Ventana")


def test_reply_with_a_memory_proposal():
    reply = parse_reply(
        '{"respuesta": "Gracias.", "propuesta_memoria": {"categoria": "carrier_rule", "hecho": "SEUR ya no cubre X.",'
        ' "cita_usuario": "SEUR ya no cubre", "transportista": "SEUR", "pais": "ES"}}'
    )

    assert reply.proposal.category == "carrier_rule" and reply.proposal.carrier == "SEUR"


def test_malformed_proposal_is_dropped_but_the_answer_is_kept():
    assert parse_reply('{"respuesta": "Gracias.", "propuesta_memoria": {"categoria": "x"}}') == AgentReply(
        answer="Gracias."
    )


def test_plain_text_reply_is_kept_without_proposal_and_empty_reply_fails():
    assert parse_reply("Son 30 días.") == AgentReply(answer="Son 30 días.")
    with pytest.raises(RagServiceError):
        parse_reply('{"respuesta": "", "propuesta_memoria": null}')


def test_generation_prompt_carries_the_memory_criteria_and_asks_for_json(monkeypatch):
    sent = {}

    class Completions:
        def create(self, **kwargs):
            sent.update(kwargs)
            message = type("M", (), {"content": '{"respuesta": "Ok.", "propuesta_memoria": null}'})
            return type("C", (), {"choices": [type("Ch", (), {"message": message})]})

    client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})})
    monkeypatch.setattr(self_evaluation, "get_llm_client", lambda: client)
    monkeypatch.setattr(self_evaluation, "load_settings", lambda: type("S", (), {"generation_model": "gen"}))

    assert self_evaluation.generate_reply("¿Ventana?", [CHUNK]) == AgentReply(answer="Ok.")
    assert sent["response_format"] == {"type": "json_object"}
    system = sent["messages"][0]["content"]
    assert system.startswith(prompt.SYSTEM_PROMPT) and "propuesta_memoria" in system and "Nunca propones" in system


# --- Clasificación de la decisión -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("classification", "outcome", "reason", "fact", "follow_up"),
    [
        (classified("approve"), "approved", "user_approved", SEUR_DRAFT.fact, ""),
        (classified("approve", follow_up="¿Y la ventana?"), "approved", "user_approved", SEUR_DRAFT.fact,
         "¿Y la ventana?"),
        (classified("reject"), "rejected", "user_rejected", None, ""),
        (classified("edit", edited="SEUR no cubre la zona rural de Zaragoza desde septiembre."), "edited",
         "user_edited", "SEUR no cubre la zona rural de Zaragoza desde septiembre.", ""),
        (classified("edit", edited="SEUR entrega en Calle Mayor 12."), "discarded", "blocked:customer_location",
         None, ""),
        (classified("edit"), "discarded", "edit_without_fact", None, ""),
        (classified("approve", confidence=0.5), "discarded", "ambiguous", None, ""),
        (classified("unrelated", follow_up="algo"), "discarded", "unrelated", None, "MENSAJE"),
        (decision.UNDECIDED, "discarded", "classifier_unavailable", None, "MENSAJE"),
    ],
    ids=["approve", "approve-and-ask", "reject", "edit", "edit-forbidden", "edit-empty", "low-confidence",
         "topic-change", "classifier-down"],
)
def test_only_a_clear_approval_or_edit_writes_and_doubt_discards(classification, outcome, reason, fact, follow_up):
    resolution = decision.resolve(classification, proposal_for(SEUR_DRAFT, SEUR_MESSAGE), "MENSAJE")

    assert (resolution.outcome, resolution.reason, resolution.fact, resolution.follow_up) == (
        outcome, reason, fact, follow_up
    )


def test_classifier_failure_never_approves(monkeypatch):
    def broken():
        raise openai.APIConnectionError(request=None)

    monkeypatch.setattr(decision, "get_llm_client", broken)

    assert decision.classify_decision("sí", proposal_for(SEUR_DRAFT, SEUR_MESSAGE)) == decision.UNDECIDED


# --- Almacén: consolidación y limpieza --------------------------------------------------------------


def test_consolidation_groups_by_subject_and_supersedes_a_near_duplicate(store):
    first = proposal_for(SEUR_DRAFT, SEUR_MESSAGE)
    store.consolidate(first, first.fact, NOW)
    second = proposal_for(SEUR_DRAFT, SEUR_MESSAGE, now=NOW + timedelta(days=1))
    store.consolidate(second, "SEUR ya no cubre la zona rural de Zaragoza; usar el transportista local.", NOW)

    (entry,) = store.entries()
    assert [fact.proposal_id for fact in entry.facts] == [second.proposal_id]
    assert ("superseded", None) in events(store)


def test_a_subject_keeps_at_most_three_facts(store):
    facts = ["SEUR no cubre Teruel rural.", "SEUR no recoge los sábados.", "SEUR tarda 72 horas a Huesca.",
             "SEUR no entrega en Monegros."]
    for number, fact in enumerate(facts):
        store.consolidate(proposal_for(SEUR_DRAFT, SEUR_MESSAGE), fact, NOW + timedelta(minutes=number))

    (entry,) = store.entries()
    assert [fact.fact for fact in entry.facts] == facts[1:]
    assert events(store).count(("evicted", None)) == 1


def test_a_category_keeps_its_most_recent_subjects(store, monkeypatch):
    monkeypatch.setitem(policy.MAX_SUBJECTS, "incident_context", 2)
    for number, zone in enumerate(["Los Ángeles", "San Diego", "Long Beach"]):
        draft = STRIKE_DRAFT.model_copy(update={"zone": zone})
        store.consolidate(proposal_for(draft, STRIKE_MESSAGE), f"Retrasos en {zone}.", NOW + timedelta(hours=number))

    assert [entry.subject for entry in store.entries()] == ["Long Beach (US)", "San Diego (US)"]


def test_expired_facts_are_forgotten_and_logged(store):
    proposal = proposal_for(STRIKE_DRAFT, STRIKE_MESSAGE)
    store.consolidate(proposal, proposal.fact, NOW)

    assert store.recall("retrasos en Los Ángeles", NOW + timedelta(days=13))
    assert store.recall("retrasos en Los Ángeles", NOW + policy.FACT_TTL["incident_context"]) == []
    assert store.entries() == []
    assert ("expired_memory", None) in events(store)


def test_recall_returns_only_relevant_entries(store):
    for draft, message in ((SEUR_DRAFT, SEUR_MESSAGE), (COSMETICS_DRAFT, COSMETICS_MESSAGE)):
        proposal = proposal_for(draft, message)
        store.consolidate(proposal, proposal.fact, NOW)

    assert [e.subject_key for e in store.recall("¿Qué transportista uso en la zona rural de Zaragoza?", NOW)] == [
        "carrier_rule:seur:ES"
    ]
    assert [e.subject_key for e in store.recall("¿Envío urgente con SEUR?", NOW)] == ["carrier_rule:seur:ES"]
    assert store.recall("¿Cuál es la ventana de devolución estándar?", NOW) == []


def test_one_pending_proposal_per_user_and_only_in_its_conversation(store):
    first = proposal_for(SEUR_DRAFT, SEUR_MESSAGE)

    assert store.open_pending(first) is True
    assert store.open_pending(proposal_for(STRIKE_DRAFT, STRIKE_MESSAGE, conversation_id="conv-2")) is False
    assert store.pending_for(USER, "conv-2", NOW) is None
    assert store.pending_for(USER, "conv-1", NOW) == first


def test_unanswered_proposal_expires_as_discarded(store):
    store.open_pending(proposal_for(SEUR_DRAFT, SEUR_MESSAGE))

    assert store.pending_for(USER, "conv-1", NOW + policy.PENDING_TTL) is None
    decisions = [event for event in store.audit_log() if event["event"] == "decision"]
    assert [(d["outcome"], d["reason"]) for d in decisions] == [("discarded", "expired_without_answer")]


def test_redis_down_is_a_clear_memory_error():
    server = fakeredis.FakeServer()
    server.connected = False
    with pytest.raises(MemoryUnavailableError):
        MemoryStore(fakeredis.FakeRedis(server=server, decode_responses=True)).recall("SEUR", NOW)


# --- Ciclos completos por el grafo ------------------------------------------------------------------


def test_approved_cycle_is_audited_and_reflected_in_a_later_conversation(compiled, agent, store):
    agent["replies"][SEUR_MESSAGE] = AgentReply(answer="Gracias por el aviso.", proposal=SEUR_DRAFT)
    agent["decisions"]["Sí, guárdalo."] = classified("approve")

    first = turn(compiled, SEUR_MESSAGE)
    assert first.state["answer"].endswith(nodes.PROPOSAL_QUESTION.format(fact=SEUR_DRAFT.fact))
    assert store.entries() == []  # proponer no escribe nada

    second = turn(compiled, "Sí, guárdalo.")
    assert second.state["answer"] == nodes.DECISION_NOTICES["approved"].format(fact=SEUR_DRAFT.fact)
    assert executed_nodes(load_trace(second.trace_path)) == [
        nodes.RECEIVE_QUESTION, nodes.INPUT_GUARD, nodes.LOAD_PENDING_PROPOSAL, nodes.RESOLVE_PROPOSAL,
    ]

    later = turn(compiled, "¿Qué transportista uso en la zona rural de Zaragoza?", conversation_id="conv-2")
    (memory,) = later.state["memories"]
    assert memory["section"] == "Memoria aprobada › Transportistas › SEUR (ES)"
    assert agent["generated"][-1][1] == [CHUNK, memory]
    assert load_trace(later.trace_path)["sources_used"] == ["agent_memory", "rag"]

    audit = store.audit_log()
    assert [(event["event"], event.get("outcome")) for event in audit] == [("proposed", None), ("decision", "approved")]
    proposed, decided = audit
    assert proposed["user_id"] == decided["user_id"] == USER
    assert proposed["source_message"] == policy.redact(SEUR_MESSAGE)
    assert decided["message"] == policy.redact("Sí, guárdalo.") and decided["label"] == "approve"
    (entry,) = store.entries()
    assert entry.facts[0].approved_by == USER and entry.facts[0].proposal_id == proposed["proposal_id"]


def test_rejected_cycle_leaves_memory_unchanged_but_audited(compiled, agent, store):
    agent["replies"][STRIKE_MESSAGE] = AgentReply(answer="Entendido.", proposal=STRIKE_DRAFT)
    agent["decisions"]["No, no lo guardes."] = classified("reject")

    turn(compiled, STRIKE_MESSAGE)
    rejected = turn(compiled, "No, no lo guardes.")
    later = turn(compiled, "¿Por qué hay retrasos en Los Ángeles?", conversation_id="conv-2")

    assert rejected.state["memory_decision"]["outcome"] == "rejected"
    assert store.entries() == []
    assert later.state["memories"] == []
    assert events(store) == [("proposed", None), ("decision", "rejected")]


def test_answering_the_proposal_and_asking_something_else_in_the_same_message(compiled, agent, store):
    agent["replies"][COSMETICS_MESSAGE] = AgentReply(answer="Tomo nota.", proposal=COSMETICS_DRAFT)
    message = "Sí, recuérdalo. Y por cierto, ¿cuál es la ventana de devolución?"
    agent["decisions"][message] = classified("approve", follow_up="¿cuál es la ventana de devolución?")

    turn(compiled, COSMETICS_MESSAGE)
    run = turn(compiled, message)

    assert run.state["question"] == "¿cuál es la ventana de devolución?"
    assert run.state["answer"] == "\n\n".join(
        [nodes.DECISION_NOTICES["approved"].format(fact=COSMETICS_DRAFT.fact),
         "Respuesta a: ¿cuál es la ventana de devolución?\nFuente: Cobertura"]
    )
    assert len(store.entries()) == 1


def test_changing_topic_discards_the_proposal_and_answers_the_new_question(compiled, agent, store):
    agent["replies"][SEUR_MESSAGE] = AgentReply(answer="Gracias.", proposal=SEUR_DRAFT)
    message = "¿Cuánto cuesta almacenar un palé en Zaragoza?"
    agent["decisions"][message] = classified("unrelated", confidence=0.9)

    turn(compiled, SEUR_MESSAGE)
    run = turn(compiled, message)

    assert run.state["memory_decision"]["outcome"] == "discarded"
    assert run.state["answer"].endswith(f"Respuesta a: {message}\nFuente: Cobertura")
    assert store.entries() == [] and store.pending_for(USER, "conv-1", NOW) is None


def test_no_second_proposal_while_one_is_pending(compiled, agent, store):
    agent["replies"][SEUR_MESSAGE] = AgentReply(answer="Gracias.", proposal=SEUR_DRAFT)
    agent["replies"][STRIKE_MESSAGE] = AgentReply(answer="Entendido.", proposal=STRIKE_DRAFT)

    turn(compiled, SEUR_MESSAGE)
    other = turn(compiled, STRIKE_MESSAGE, conversation_id="conv-2")

    assert other.state["memory_proposal"] is None
    assert "¿Quieres que recuerde" not in other.state["answer"]
    assert events(store)[-1] == ("skipped", None)


def test_blocked_candidate_is_not_proposed_and_its_audit_is_redacted(compiled, agent, store):
    message = "El destinatario de SEUR siempre recibe en Calle Mayor 12, 50001 Zaragoza."
    agent["replies"][message] = AgentReply(
        answer="Gracias.",
        proposal=SEUR_DRAFT.model_copy(update={"fact": message, "user_quote": message}),
    )

    run = turn(compiled, message)

    assert run.state["memory_proposal"] is None and "¿Quieres que recuerde" not in run.state["answer"]
    (blocked,) = store.audit_log()
    assert blocked["event"] == "blocked" and "customer_location" in blocked["violations"]
    assert "mayor 12" not in blocked["fact"] and "50001" not in blocked["message"]


def test_without_an_authenticated_user_nothing_is_proposed(compiled, agent, store):
    agent["replies"][SEUR_MESSAGE] = AgentReply(answer="Gracias.", proposal=SEUR_DRAFT)

    run = turn(compiled, SEUR_MESSAGE, user_id=None)

    assert run.state["memory_proposal"] is None and store.audit_log() == []


def test_unavailable_memory_does_not_stop_the_answer_and_says_so(compiled, agent):
    server = fakeredis.FakeServer()
    server.connected = False
    use_memory_store(MemoryStore(fakeredis.FakeRedis(server=server, decode_responses=True)))

    run = turn(compiled, "¿Ventana de devolución?")

    assert run.state["answer"] == f"{nodes.MEMORY_UNAVAILABLE}\n\nRespuesta a: ¿Ventana de devolución?\nFuente: Cobertura"
