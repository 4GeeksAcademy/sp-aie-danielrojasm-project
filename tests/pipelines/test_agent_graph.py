"""Grafo del agente: compilación, enrutado, contrato de nodos, checkpoints y trace.

Sin servicios reales: `retrieve()` y `generate_answer()` de `data/pipelines/rag.py` se sustituyen por dobles que
registran sus llamadas. Cada test compila su propio grafo con un `InMemorySaver` nuevo.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END

from data.pipelines import rag
from data.process.rag import RagServiceError
from services.support_agent import nodes
from services.support_agent.graph import AgentGraphError, compile_graph, define_graph, graph
from services.support_agent.runner import AgentRunError, resume_run, run_agent
from services.support_agent.tracing import executed_nodes, load_trace, trace_dir


CHUNK = {"source_document": "returns-policy", "section": "Ventana", "chunk_index": 1, "text": "30 días."}


@pytest.fixture
def calls(monkeypatch):
    """Sustituye las piezas del RAG; `calls` registra el orden y los argumentos."""
    log: list[tuple] = []
    monkeypatch.setattr(rag, "retrieve", lambda question: log.append(("retrieve", question)) or [CHUNK])
    monkeypatch.setattr(
        rag, "generate_answer", lambda question, context: log.append(("generate", question, context)) or "Son 30 días."
    )
    monkeypatch.setattr(rag, "query", lambda question: pytest.fail("ningún nodo debe llamar a query()"))
    return log


@pytest.fixture
def compiled():
    return compile_graph(define_graph(), checkpointer=InMemorySaver())


# --- Compilación --------------------------------------------------------------------------------


def test_module_graph_is_compiled_with_a_checkpointer():
    assert graph.checkpointer is not None
    assert set(graph.get_graph().nodes) >= {
        nodes.RECEIVE_QUESTION,
        nodes.REJECT_QUESTION,
        nodes.RETRIEVE,
        nodes.GENERATE_ANSWER,
        nodes.NO_INFORMATION,
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

    assert edges[(nodes.RECEIVE_QUESTION, nodes.REJECT_QUESTION)] is True
    assert edges[(nodes.RECEIVE_QUESTION, nodes.RETRIEVE)] is True
    assert edges[(nodes.RETRIEVE, nodes.GENERATE_ANSWER)] is True
    assert edges[(nodes.RETRIEVE, nodes.NO_INFORMATION)] is True
    assert edges[(nodes.GENERATE_ANSWER, END)] is False


# --- Enrutado y contrato de nodos -----------------------------------------------------------------


def test_question_with_context_is_retrieved_once_and_generated_from_that_context(compiled, calls):
    run = run_agent("  ¿Ventana de devolución?  ", compiled=compiled)

    assert calls == [("retrieve", "¿Ventana de devolución?"), ("generate", "¿Ventana de devolución?", [CHUNK])]
    assert run.state == {"question": "¿Ventana de devolución?", "context": [CHUNK], "answer": "Son 30 días."}


def test_empty_question_ends_with_an_error_without_retrieving(compiled, calls):
    run = run_agent("   ", compiled=compiled)

    assert calls == []
    assert run.state == {"question": "", "error": nodes.EMPTY_QUESTION_ERROR}


def test_no_context_answers_honestly_without_calling_the_model(compiled, calls, monkeypatch):
    monkeypatch.setattr(rag, "retrieve", lambda question: calls.append(("retrieve", question)) or [])

    run = run_agent("¿Almacén en Ciudad de México?", compiled=compiled)

    assert calls == [("retrieve", "¿Almacén en Ciudad de México?")]
    assert run.state["answer"] == nodes.NO_INFORMATION_ANSWER


# --- Trace y checkpoints --------------------------------------------------------------------------


def test_each_run_writes_a_queryable_trace(compiled, calls):
    run = run_agent("¿Ventana de devolución?", compiled=compiled)

    assert run.trace_path.parent == trace_dir()
    trace = load_trace(run.trace_path)
    assert trace["run_id"] == run.run_id
    assert trace["status"] == "completed"
    assert executed_nodes(trace) == [nodes.RECEIVE_QUESTION, nodes.RETRIEVE, nodes.GENERATE_ANSWER]
    assert [step["order"] for step in trace["steps"]] == [1, 2, 3]
    assert trace["steps"][1]["output"] == {"context": [CHUNK]}
    assert trace["final_state"] == run.state
    assert [checkpoint["next"] for checkpoint in trace["checkpoints"]] == [
        ["__start__"],
        [nodes.RECEIVE_QUESTION],
        [nodes.RETRIEVE],
        [nodes.GENERATE_ANSWER],
        [],
    ]


def test_completed_run_releases_its_checkpoint_thread(compiled, calls):
    run = run_agent("¿Ventana de devolución?", compiled=compiled)

    assert compiled.get_state({"configurable": {"thread_id": run.run_id}}).values == {}


def test_failed_node_is_traced_and_the_run_resumes_from_its_last_checkpoint(compiled, calls, monkeypatch):
    def unavailable(question, context):
        raise RagServiceError("El modelo de generación no respondió.")

    monkeypatch.setattr(rag, "generate_answer", unavailable)

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
    assert executed_nodes(failed) == [nodes.RECEIVE_QUESTION, nodes.RETRIEVE]
    assert failed["checkpoints"][-1]["next"] == [nodes.GENERATE_ANSWER]

    monkeypatch.setattr(rag, "generate_answer", lambda question, context: "Son 30 días.")
    run = resume_run("run-1", compiled=compiled)

    assert calls == [("retrieve", "¿Ventana de devolución?")]  # retrieve no se repite al retomar
    assert run.state["answer"] == "Son 30 días."
    resumed = load_trace(run.trace_path)
    assert resumed["status"] == "completed" and resumed["resumed"] == 1 and "error" not in resumed
    assert executed_nodes(resumed) == [nodes.RECEIVE_QUESTION, nodes.RETRIEVE, nodes.GENERATE_ANSWER]
