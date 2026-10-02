"""Grafo del agente: compilación, enrutado entre RAG y tool, contrato de nodos, fallback, checkpoints y trace.

Sin servicios reales: `retrieve()` de `data/pipelines/rag.py`, la generación con auto-evaluación (`generate_reply`),
el enrutador (`plan_route`) y la tool de tickets (`get_ticket`) se sustituyen por dobles que registran sus llamadas.
La memoria es el Redis en memoria de `tests/conftest.py` (vacía: ningún test de este módulo la usa). Cada test compila su propio
grafo con un `InMemorySaver` nuevo.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END

from data.pipelines import rag
from data.process.rag import RagServiceError
from services.support_agent import nodes
from services.support_agent.graph import AgentGraphError, compile_graph, define_graph, graph
from services.support_agent.memory.self_evaluation import AgentReply
from services.support_agent.routing import RoutePlan
from services.support_agent.runner import AgentRunError, resume_run, run_agent
from services.support_agent.tools.incidents import Ticket, TicketLookup
from services.support_agent.tracing import executed_nodes, load_trace, trace_dir


CHUNK = {"source_document": "returns-policy", "section": "Ventana", "chunk_index": 1, "text": "30 días."}
REPLY = AgentReply(answer="Son 30 días.\nFuente: Ventana")
KNOWLEDGE_ONLY = RoutePlan(ticket_ids=[], needs_knowledge=True, decided_by="llm")
TICKET = Ticket(
    id=482,
    title="Paquete perdido en Zaragoza",
    description="El cliente no recibió el pedido.",
    status="in_progress",
    category="lost_parcel",
    origin="customer",
    branch="zaragoza_office",
    created_at="2026-09-01T10:00:00+00:00",
    updated_at="2026-09-02T12:00:00+00:00",
)


@pytest.fixture
def calls(monkeypatch):
    """Sustituye RAG, enrutador y tool; `calls` registra el orden y los argumentos. Por defecto, solo RAG."""
    log: list[tuple] = []
    monkeypatch.setattr(rag, "retrieve", lambda question: log.append(("retrieve", question)) or [CHUNK])
    monkeypatch.setattr(
        nodes, "generate_reply", lambda question, context: log.append(("generate", question, context)) or REPLY
    )
    monkeypatch.setattr(rag, "query", lambda question: pytest.fail("ningún nodo debe llamar a query()"))
    monkeypatch.setattr(nodes, "plan_route", lambda question: KNOWLEDGE_ONLY)
    monkeypatch.setattr(nodes, "get_ticket", lambda query: pytest.fail("esta pregunta no debe usar la tool"))
    return log


def route_to(monkeypatch, ticket_ids: list[int], needs_knowledge: bool) -> None:
    plan = RoutePlan(ticket_ids=ticket_ids, needs_knowledge=needs_knowledge, decided_by="llm")
    monkeypatch.setattr(nodes, "plan_route", lambda question: plan)


def tool_returns(monkeypatch, calls: list[tuple], **lookups: TicketLookup) -> None:
    def get_ticket(query):
        calls.append(("lookup", query.ticket_id))
        return lookups[str(query.ticket_id)]

    monkeypatch.setattr(nodes, "get_ticket", get_ticket)


def found(ticket: Ticket = TICKET) -> TicketLookup:
    return TicketLookup(ticket_id=ticket.id, outcome="found", ticket=ticket)


@pytest.fixture
def compiled():
    return compile_graph(define_graph(), checkpointer=InMemorySaver())


# --- Compilación --------------------------------------------------------------------------------


def test_module_graph_is_compiled_with_a_checkpointer():
    assert graph.checkpointer is not None
    assert set(graph.get_graph().nodes) >= {
        nodes.RECEIVE_QUESTION,
        nodes.REJECT_QUESTION,
        nodes.INPUT_GUARD,
        nodes.GUARDRAIL_REFUSAL,
        nodes.SMALL_TALK_REPLY,
        nodes.LOAD_PENDING_PROPOSAL,
        nodes.RESOLVE_PROPOSAL,
        nodes.RECALL_MEMORY,
        nodes.ROUTE_QUESTION,
        nodes.LOOKUP_TICKETS,
        nodes.RETRIEVE,
        nodes.GENERATE_ANSWER,
        nodes.TICKET_FALLBACK,
        nodes.NO_INFORMATION,
        nodes.PROPOSE_MEMORY,
        nodes.OUTPUT_GUARD,
    }


def test_compilation_fails_clearly_for_a_node_without_connections():
    builder = define_graph()
    builder.add_node("orphan", lambda state: {})

    with pytest.raises(AgentGraphError, match="sin conexión desde START: orphan"):
        compile_graph(builder)


def test_compilation_fails_clearly_for_a_node_without_a_path_to_end():
    builder = define_graph()
    builder.add_node("dead_end", lambda state: {})
    builder.add_edge(nodes.NO_INFORMATION, "dead_end")

    with pytest.raises(AgentGraphError, match="sin camino hasta END: dead_end"):
        compile_graph(builder)


def test_compilation_fails_clearly_for_an_edge_to_an_unknown_node():
    builder = define_graph()
    builder.add_edge(nodes.REJECT_QUESTION, "missing")

    with pytest.raises(AgentGraphError, match="unknown node `missing`"):
        compile_graph(builder)


def test_routes_are_exit_conditions_not_a_fixed_sequence():
    edges = {(edge.source, edge.target): edge.conditional for edge in graph.get_graph().edges}

    for source, target in [
        (nodes.RECEIVE_QUESTION, nodes.REJECT_QUESTION),
        (nodes.RECEIVE_QUESTION, nodes.INPUT_GUARD),
        (nodes.INPUT_GUARD, nodes.GUARDRAIL_REFUSAL),
        (nodes.INPUT_GUARD, nodes.LOAD_PENDING_PROPOSAL),
        (nodes.LOAD_PENDING_PROPOSAL, nodes.RESOLVE_PROPOSAL),
        (nodes.LOAD_PENDING_PROPOSAL, nodes.SMALL_TALK_REPLY),
        (nodes.LOAD_PENDING_PROPOSAL, nodes.RECALL_MEMORY),
        (nodes.RESOLVE_PROPOSAL, nodes.SMALL_TALK_REPLY),
        (nodes.RESOLVE_PROPOSAL, nodes.RECALL_MEMORY),
        (nodes.RESOLVE_PROPOSAL, END),
        (nodes.ROUTE_QUESTION, nodes.LOOKUP_TICKETS),
        (nodes.ROUTE_QUESTION, nodes.RETRIEVE),
        (nodes.LOOKUP_TICKETS, nodes.RETRIEVE),
        (nodes.LOOKUP_TICKETS, nodes.GENERATE_ANSWER),
        (nodes.LOOKUP_TICKETS, nodes.TICKET_FALLBACK),
        (nodes.RETRIEVE, nodes.GENERATE_ANSWER),
        (nodes.RETRIEVE, nodes.TICKET_FALLBACK),
        (nodes.RETRIEVE, nodes.NO_INFORMATION),
        (nodes.OUTPUT_GUARD, nodes.PROPOSE_MEMORY),
        (nodes.OUTPUT_GUARD, END),
    ]:
        assert edges[(source, target)] is True, (source, target)
    # Toda respuesta pasa por el guard de salida: es una arista fija, no una condición.
    for answered in (nodes.GENERATE_ANSWER, nodes.NO_INFORMATION, nodes.TICKET_FALLBACK, nodes.SMALL_TALK_REPLY):
        assert edges[(answered, nodes.OUTPUT_GUARD)] is False
    assert edges[(nodes.RECALL_MEMORY, nodes.ROUTE_QUESTION)] is False
    assert edges[(nodes.GUARDRAIL_REFUSAL, END)] is False
    assert edges[(nodes.PROPOSE_MEMORY, END)] is False


# --- Enrutado y contrato de nodos -----------------------------------------------------------------


def test_knowledge_question_is_retrieved_once_and_generated_from_that_context(compiled, calls):
    run = run_agent("  ¿Ventana de devolución?  ", compiled=compiled)

    assert calls == [("retrieve", "¿Ventana de devolución?"), ("generate", "¿Ventana de devolución?", [CHUNK])]
    assert run.state["answer"] == REPLY.answer
    assert run.state["route"] == KNOWLEDGE_ONLY.model_dump()


def test_empty_question_ends_with_an_error_without_consulting_any_source(compiled, calls, monkeypatch):
    monkeypatch.setattr(nodes, "plan_route", lambda question: pytest.fail("no debe enrutar"))

    run = run_agent("   ", compiled=compiled)

    assert calls == []
    assert run.state["error"] == nodes.EMPTY_QUESTION_ERROR
    assert "answer" not in run.state and "memories" not in run.state


def test_no_context_answers_with_the_fixed_text_and_only_self_evaluates_memory(compiled, calls, monkeypatch):
    monkeypatch.setattr(rag, "retrieve", lambda question: calls.append(("retrieve", question)) or [])

    run = run_agent("¿Almacén en Ciudad de México?", compiled=compiled)

    # El modelo solo ve el mensaje sin contexto (auto-evaluación); su texto no sustituye la respuesta fija.
    assert calls == [("retrieve", "¿Almacén en Ciudad de México?"), ("generate", "¿Almacén en Ciudad de México?", [])]
    assert run.state["answer"] == nodes.NO_INFORMATION_ANSWER


def test_no_context_keeps_the_fixed_answer_when_the_model_is_down(compiled, calls, monkeypatch):
    def unavailable(question, context):
        raise RagServiceError("El modelo de generación no respondió.")

    monkeypatch.setattr(rag, "retrieve", lambda question: [])
    monkeypatch.setattr(nodes, "generate_reply", unavailable)

    run = run_agent("¿Almacén en Ciudad de México?", compiled=compiled)

    assert run.state["answer"] == nodes.NO_INFORMATION_ANSWER
    assert run.state["memory_candidate"] is None


def test_ticket_question_uses_the_tool_and_not_the_rag(compiled, calls, monkeypatch):
    route_to(monkeypatch, [482], needs_knowledge=False)
    tool_returns(monkeypatch, calls, **{"482": found()})

    run = run_agent("¿En qué estado está el ticket 482?", compiled=compiled)

    assert [call[0] for call in calls] == ["lookup", "generate"]
    (fragment,) = calls[1][2]
    assert fragment["section"] == "Gestor de incidencias › Ticket 482"
    assert "Estado: en curso (in_progress)" in fragment["text"]
    assert run.state["answer"] == REPLY.answer
    assert load_trace(run.trace_path)["sources_used"] == ["incidents_tool"]


def test_mixed_question_uses_the_tool_then_the_rag(compiled, calls, monkeypatch):
    route_to(monkeypatch, [482], needs_knowledge=True)
    tool_returns(monkeypatch, calls, **{"482": found()})

    run = run_agent("¿Estado del ticket 482 y ventana de devolución?", compiled=compiled)

    assert [call[0] for call in calls] == ["lookup", "retrieve", "generate"]
    context = calls[2][2]
    assert context[0] == CHUNK and context[1]["source_document"] == "incident-manager"
    assert load_trace(run.trace_path)["sources_used"] == ["incidents_tool", "rag"]


# --- Fallback de la tool ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        ("not_found", "No encuentro el ticket 482 en el gestor de incidencias"),
        ("timeout", "No pude confirmar el estado del ticket 482 ahora mismo"),
        ("unavailable", "No pude confirmar el estado del ticket 482 ahora mismo"),
    ],
)
def test_unconfirmed_ticket_falls_back_without_inventing_a_status(compiled, calls, monkeypatch, outcome, message):
    route_to(monkeypatch, [482], needs_knowledge=False)
    tool_returns(monkeypatch, calls, **{"482": TicketLookup(ticket_id=482, outcome=outcome)})

    run = run_agent("¿En qué estado está el ticket 482?", compiled=compiled)

    assert calls == [("lookup", 482)]  # el modelo no llega a ver la pregunta
    assert executed_nodes(load_trace(run.trace_path))[-2:] == [nodes.TICKET_FALLBACK, nodes.OUTPUT_GUARD]
    assert run.state["answer"].startswith(message)
    assert run.state["answer"].endswith(nodes.TICKET_FALLBACK_SOURCE)


def test_unconfirmed_ticket_keeps_the_knowledge_answer_and_warns_about_the_ticket(compiled, calls, monkeypatch):
    route_to(monkeypatch, [482], needs_knowledge=True)
    tool_returns(monkeypatch, calls, **{"482": TicketLookup(ticket_id=482, outcome="timeout")})

    run = run_agent("¿Estado del ticket 482 y ventana de devolución?", compiled=compiled)

    assert [call[0] for call in calls] == ["lookup", "retrieve", "generate"]
    assert calls[2][2] == [CHUNK]  # el ticket sin confirmar no llega al modelo
    assert run.state["answer"] == nodes.TICKET_UNCONFIRMED.format(ticket_id=482) + "\n" + REPLY.answer


def test_unconfirmed_ticket_and_no_context_falls_back_for_both_parts(compiled, calls, monkeypatch):
    route_to(monkeypatch, [482], needs_knowledge=True)
    tool_returns(monkeypatch, calls, **{"482": TicketLookup(ticket_id=482, outcome="unavailable")})
    monkeypatch.setattr(rag, "retrieve", lambda question: calls.append(("retrieve", question)) or [])

    run = run_agent("¿Estado del ticket 482 y seguro de mercancía?", compiled=compiled)

    assert [call[0] for call in calls] == ["lookup", "retrieve"]
    assert nodes.KNOWLEDGE_ALSO_MISSING in run.state["answer"]


def test_only_confirmed_tickets_reach_the_model(compiled, calls, monkeypatch):
    route_to(monkeypatch, [482, 7], needs_knowledge=False)
    tool_returns(monkeypatch, calls, **{"482": found(), "7": TicketLookup(ticket_id=7, outcome="not_found")})

    run = run_agent("¿Estado de los tickets 482 y 7?", compiled=compiled)

    assert [fragment["chunk_index"] for fragment in calls[-1][2]] == [482]
    assert run.state["answer"].startswith(nodes.TICKET_NOT_FOUND.format(ticket_id=7))


# --- Trace y checkpoints --------------------------------------------------------------------------


def test_each_run_writes_a_queryable_trace(compiled, calls):
    run = run_agent("¿Ventana de devolución?", compiled=compiled)

    assert run.trace_path.parent == trace_dir()
    trace = load_trace(run.trace_path)
    assert trace["run_id"] == run.run_id
    assert trace["status"] == "completed"
    assert trace["sources_used"] == ["rag"]
    assert executed_nodes(trace) == [
        nodes.RECEIVE_QUESTION,
        nodes.INPUT_GUARD,
        nodes.LOAD_PENDING_PROPOSAL,
        nodes.RECALL_MEMORY,
        nodes.ROUTE_QUESTION,
        nodes.RETRIEVE,
        nodes.GENERATE_ANSWER,
        nodes.OUTPUT_GUARD,
    ]
    assert [step["order"] for step in trace["steps"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert trace["steps"][1]["output"]["guardrail"]["category"] == "in_scope"
    assert trace["steps"][3]["output"] == {"memories": []}
    assert trace["steps"][4]["output"] == {"route": KNOWLEDGE_ONLY.model_dump()}
    assert trace["steps"][5]["output"] == {"context": [CHUNK]}
    assert trace["final_state"] == run.state
    assert trace["final_state"]["guardrail_events"] == []
    assert [checkpoint["next"] for checkpoint in trace["checkpoints"]] == [
        ["__start__"],
        [nodes.RECEIVE_QUESTION],
        [nodes.INPUT_GUARD],
        [nodes.LOAD_PENDING_PROPOSAL],
        [nodes.RECALL_MEMORY],
        [nodes.ROUTE_QUESTION],
        [nodes.RETRIEVE],
        [nodes.GENERATE_ANSWER],
        [nodes.OUTPUT_GUARD],
        [],
    ]


def test_completed_run_releases_its_checkpoint_thread(compiled, calls):
    run = run_agent("¿Ventana de devolución?", compiled=compiled)

    assert compiled.get_state({"configurable": {"thread_id": run.run_id}}).values == {}


def test_failed_node_is_traced_and_the_run_resumes_from_its_last_checkpoint(compiled, calls, monkeypatch):
    def unavailable(question, context):
        raise RagServiceError("El modelo de generación no respondió.")

    monkeypatch.setattr(nodes, "generate_reply", unavailable)

    with pytest.raises(AgentRunError) as failure:
        run_agent("¿Ventana de devolución?", compiled=compiled, run_id="run-1")

    assert failure.value.node == nodes.GENERATE_ANSWER
    assert isinstance(failure.value.__cause__, RagServiceError)
    failed = load_trace(failure.value.trace_path)
    assert failed["status"] == "failed"
    assert failed["error"] == {
        "node": nodes.GENERATE_ANSWER,
        "type": "RagServiceError",
        "message": "El modelo de generación no respondió.",
    }
    assert executed_nodes(failed) == [
        nodes.RECEIVE_QUESTION,
        nodes.INPUT_GUARD,
        nodes.LOAD_PENDING_PROPOSAL,
        nodes.RECALL_MEMORY,
        nodes.ROUTE_QUESTION,
        nodes.RETRIEVE,
    ]
    assert failed["checkpoints"][-1]["next"] == [nodes.GENERATE_ANSWER]

    monkeypatch.setattr(nodes, "generate_reply", lambda question, context: REPLY)
    run = resume_run("run-1", compiled=compiled)

    assert calls == [("retrieve", "¿Ventana de devolución?")]  # retrieve no se repite al retomar
    assert run.state["answer"] == REPLY.answer
    resumed = load_trace(run.trace_path)
    assert resumed["status"] == "completed" and resumed["resumed"] == 1 and "error" not in resumed
    assert executed_nodes(resumed) == [
        nodes.RECEIVE_QUESTION,
        nodes.INPUT_GUARD,
        nodes.LOAD_PENDING_PROPOSAL,
        nodes.RECALL_MEMORY,
        nodes.ROUTE_QUESTION,
        nodes.RETRIEVE,
        nodes.GENERATE_ANSWER,
        nodes.OUTPUT_GUARD,
    ]
