"""Evals del agente LangGraph contra los traces grabados en `data/eval/agent/traces/`.

No ejecutan el agente: leen el trace de una corrida real (`scripts/record_agent_traces.py`) y comprueban el
recorrido por el grafo, los checkpoints y que la respuesta siga anclada en la base de conocimiento comercial.

    uv run pytest tests/pipelines/test_agent_evals.py -v
"""

import json
from pathlib import Path

import pytest

from services.support_agent.tracing import executed_nodes, load_trace


EVAL_DIR = Path(__file__).resolve().parents[2] / "data" / "eval" / "agent"
CASES = json.loads((EVAL_DIR / "eval-cases.json").read_text(encoding="utf-8"))["cases"]


def trace_for(case: dict) -> dict:
    return load_trace(EVAL_DIR / "traces" / f"{case['id']}.json")


def retrieved_sources(trace: dict) -> set[str]:
    (step,) = [step for step in trace["steps"] if step["node"] == "retrieve"]
    return {chunk["source_document"] for chunk in step["output"]["context"]}


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_run_follows_the_expected_path_through_the_graph(case):
    trace = trace_for(case)

    assert trace["status"] == "completed"
    assert trace["question"] == case["question"]
    assert executed_nodes(trace) == case["expected_nodes"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_generation_only_runs_after_retrieve_found_context(case):
    trace = trace_for(case)
    nodes = executed_nodes(trace)

    if "generate_answer" in nodes:
        assert nodes.index("retrieve") < nodes.index("generate_answer")
        assert trace["final_state"]["context"], "generate_answer no debe ejecutarse sobre contexto vacío"
    if "retrieve" in nodes and not trace["final_state"]["context"]:
        assert "generate_answer" not in nodes and "no_information" in nodes


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
def test_answer_is_grounded_in_the_knowledge_base(case):
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
