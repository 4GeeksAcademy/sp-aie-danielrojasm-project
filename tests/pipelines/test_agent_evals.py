"""Evals del agente LangGraph contra los traces grabados en `data/eval/agent/traces/`.

No ejecutan el agente: leen el trace de una corrida real (`scripts/record_agent_traces.py`) y comprueban el
recorrido por el grafo, qué fuentes se consultaron y en qué orden (RAG o tool de tickets), los checkpoints, el
fallback de la tool y que la respuesta siga anclada en la base de conocimiento o en el dato vivo del ticket.

    uv run pytest tests/pipelines/test_agent_evals.py -v
"""

import json
from pathlib import Path

import pytest

from services.support_agent.tools.incidents import STATUS_LABELS
from services.support_agent.tracing import executed_nodes, load_trace


EVAL_DIR = Path(__file__).resolve().parents[2] / "data" / "eval" / "agent"
CASES = json.loads((EVAL_DIR / "eval-cases.json").read_text(encoding="utf-8"))["cases"]
TICKET_CASES = [case for case in CASES if "incidents_tool" in case["expected_sources"]]


def trace_for(case: dict) -> dict:
    return load_trace(EVAL_DIR / "traces" / f"{case['id']}.json")


def retrieved_sources(trace: dict) -> set[str]:
    steps = [step for step in trace["steps"] if step["node"] == "retrieve"]
    return {chunk["source_document"] for step in steps for chunk in step["output"]["context"]}


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_run_follows_the_expected_path_through_the_graph(case):
    trace = trace_for(case)

    assert trace["status"] == "completed"
    assert trace["question"] == case["question"]
    assert executed_nodes(trace) == case["expected_nodes"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_agent_routes_to_the_expected_sources_in_order(case):
    trace = trace_for(case)

    assert trace["sources_used"] == case["expected_sources"]
    if trace["sources_used"]:
        (route,) = [step["output"]["route"] for step in trace["steps"] if step["node"] == "route_question"]
        assert route["decided_by"] == "llm"
        assert bool(route["ticket_ids"]) == ("incidents_tool" in case["expected_sources"])
        assert route["needs_knowledge"] == ("rag" in case["expected_sources"])


@pytest.mark.parametrize("case", TICKET_CASES, ids=[case["id"] for case in TICKET_CASES])
def test_ticket_answer_is_grounded_in_the_live_status_or_falls_back_honestly(case):
    trace = trace_for(case)
    answer = trace["final_state"]["answer"].lower()
    lookups = trace["final_state"]["tickets"]

    for lookup in lookups:
        if lookup["outcome"] == "found":
            label = STATUS_LABELS[lookup["ticket"]["status"]]
            # Raíz del estado ("resuelt" acepta "resuelta" y "resuelto"): el que devolvió el gestor en esa corrida.
            assert label[:-1] in answer
        else:
            assert f"ticket {lookup['ticket_id']}" in answer
            assert not any(label[:-1] in answer for label in STATUS_LABELS.values())
    if not any(lookup["outcome"] == "found" for lookup in lookups) and not trace["final_state"].get("context"):
        assert "generate_answer" not in executed_nodes(trace)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_generation_only_runs_after_its_sources_found_context(case):
    trace = trace_for(case)
    nodes = executed_nodes(trace)

    confirmed = [lookup for lookup in trace["final_state"].get("tickets", []) if lookup["outcome"] == "found"]
    if "generate_answer" in nodes:
        for source in ("retrieve", "lookup_tickets"):
            if source in nodes:
                assert nodes.index(source) < nodes.index("generate_answer")
        has_context = trace["final_state"].get("context") or confirmed
        assert has_context, "generate_answer no debe ejecutarse sin contexto ni tickets confirmados"
    if "retrieve" in nodes and not trace["final_state"]["context"] and not confirmed:
        assert "generate_answer" not in nodes


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_every_transition_left_a_checkpoint(case):
    trace = trace_for(case)
    nodes = executed_nodes(trace)
    checkpoints = trace["checkpoints"]

    # input → un checkpoint antes de cada nodo → estado final sin siguiente nodo.
    assert [checkpoint["next"] for checkpoint in checkpoints[1:-1]] == [[node] for node in nodes]
    assert checkpoints[-1]["next"] == []
    assert checkpoints[-1]["values"] == trace["final_state"]
    assert len({checkpoint["checkpoint_id"] for checkpoint in checkpoints}) == len(checkpoints)


@pytest.mark.parametrize(
    "case", [case for case in CASES if "answer_contains" in case], ids=lambda case: case["id"]
)
def test_answer_is_grounded_in_its_sources(case):
    trace = trace_for(case)
    answer = trace["final_state"]["answer"]

    for expected in case["answer_contains"]:
        assert expected in answer
    assert retrieved_sources(trace) >= set(case.get("retrieved_sources_include", []))


def test_empty_question_ends_with_a_clear_error_without_retrieving():
    (case,) = [case for case in CASES if case["id"] == "empty-question"]
    trace = trace_for(case)

    assert case["error_contains"] in trace["final_state"]["error"]
    assert "retrieve" not in executed_nodes(trace)
    assert "answer" not in trace["final_state"]
