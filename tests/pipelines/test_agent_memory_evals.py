"""Evals de la memoria del agente contra la evidencia grabada en `data/eval/agent/memory/`.

No ejecutan el agente: leen lo que grabó `scripts/record_memory_evidence.py` con el modelo, Qdrant y Redis reales y
comprueban la auto-evaluación (qué se propone y qué no), que nada se escribe sin una decisión explícita, que cada
propuesta queda auditada y que una memoria aprobada cambia una respuesta posterior.

    uv run pytest tests/pipelines/test_agent_memory_evals.py -v
"""

import json
from pathlib import Path

import pytest

from services.support_agent.memory import policy


EVAL_DIR = Path(__file__).resolve().parents[2] / "data" / "eval" / "agent"
CASES = json.loads((EVAL_DIR / "memory-cases.json").read_text(encoding="utf-8"))
SELF_EVALUATION = CASES["self_evaluation"]


def evidence(case_id: str) -> dict:
    return json.loads((EVAL_DIR / "memory" / f"{case_id}.json").read_text(encoding="utf-8"))


def audit_events(record: dict) -> list[tuple[str, str | None]]:
    return [(event["event"], event.get("outcome")) for event in record["audit"]]


def remembered(turn: dict) -> list[str]:
    return [fact["fact"] for entry in turn["memory_after"] for fact in entry["facts"]]


@pytest.mark.parametrize("case", SELF_EVALUATION, ids=[case["id"] for case in SELF_EVALUATION])
def test_agent_proposes_only_what_is_worth_remembering(case):
    (turn,) = evidence(case["id"])["turns"]

    assert bool(turn["memory_proposal"]) is case["expect_proposal"]
    if case["expect_proposal"]:
        assert turn["memory_proposal"]["category"] == case["category"]
        assert turn["answer"].endswith("Responde sí, no o corrígelo.")
    else:
        assert "¿Quieres que recuerde" not in turn["answer"]


def test_at_least_three_documented_examples_of_each_kind():
    assert sum(case["expect_proposal"] for case in SELF_EVALUATION) >= 3
    assert sum(not case["expect_proposal"] for case in SELF_EVALUATION) >= 3


@pytest.mark.parametrize("case", SELF_EVALUATION, ids=[case["id"] for case in SELF_EVALUATION])
def test_proposing_never_writes_and_is_audited(case):
    record = evidence(case["id"])
    (turn,) = record["turns"]

    assert turn["memory_after"] == []
    assert [event for event, _ in audit_events(record) if event == "proposed"] == (
        ["proposed"] if case["expect_proposal"] else []
    )
    for event in record["audit"]:
        assert not policy.forbidden_content(event.get("source_message"), event.get("proposed_fact"))


def test_approved_memory_is_reflected_in_a_later_conversation_of_another_user():
    record = evidence("approved-cycle")
    before, proposal, approval, after = record["turns"]

    assert before["memories_recalled"] == [] and "SEUR" in before["answer"]
    assert proposal["memory_proposal"]["subject_key"] == "carrier_rule:seur:ES" and proposal["memory_after"] == []
    assert approval["memory_decision"]["outcome"] == "approved"
    assert remembered(approval) == [proposal["memory_proposal"]["fact"]]
    assert after["conversation"] != proposal["conversation"] and after["user"] != proposal["user"]
    assert after["sources_used"][0] == "agent_memory"
    assert after["memories_recalled"][0]["section"].startswith("Memoria aprobada")
    assert "local" in after["answer"].lower()
    assert "Memoria aprobada › Transportistas › SEUR (ES)" in after["answer"].splitlines()[-1]

    assert audit_events(record) == [("proposed", None), ("decision", "approved")]
    proposed, decided = record["audit"]
    assert proposed["proposal_id"] == decided["proposal_id"] == approval["memory_after"][0]["facts"][0]["proposal_id"]
    assert decided["user_id"] == approval["memory_after"][0]["facts"][0]["approved_by"] == "cx-agent-1"
    assert decided["label"] == "approve" and decided["decided_by"] == "llm"


def test_rejected_memory_leaves_memory_unchanged_and_the_rejection_is_audited():
    record = evidence("rejected-cycle")
    before, proposal, rejection, after = record["turns"]

    assert proposal["memory_proposal"]["category"] == "incident_context"
    assert rejection["memory_decision"]["outcome"] == "rejected"
    # El motivo del rechazo no se trata como otra pregunta: la respuesta es solo la confirmación.
    assert rejection["nodes"][-1] == "resolve_proposal" and rejection["answer"].startswith("Entendido: no lo guardo")
    assert all(turn["memory_after"] == [] for turn in record["turns"])
    assert after["memories_recalled"] == [] and after["answer"] == before["answer"]
    assert audit_events(record) == [("proposed", None), ("decision", "rejected")]
    assert record["audit"][1]["message"] == policy.redact(rejection["message"])


def test_answering_the_proposal_and_asking_something_else_continues_the_conversation():
    record = evidence("approve-and-ask")
    _, both = record["turns"]

    assert both["memory_decision"]["outcome"] == "approved"
    assert "resolve_proposal" in both["nodes"] and "generate_answer" in both["nodes"]
    assert both["answer"].startswith("Hecho: lo recordaré") and "30 días" in both["answer"]


def test_changing_topic_discards_the_proposal_and_answers_the_new_question():
    record = evidence("topic-change")
    _, other = record["turns"]

    assert other["memory_decision"]["outcome"] == "discarded"
    assert other["memory_after"] == []
    assert "Fuente: Tarifas de Almacenamiento" in other["answer"]
    assert audit_events(record) == [("proposed", None), ("decision", "discarded")]


def test_an_edit_stores_the_user_version():
    record = evidence("edited-cycle")
    proposal, edit = record["turns"]

    assert edit["memory_decision"]["outcome"] == "edited"
    assert remembered(edit) == [edit["memory_decision"]["fact"]]
    assert remembered(edit) != [proposal["memory_proposal"]["fact"]]
    assert "septiembre" in remembered(edit)[0]
