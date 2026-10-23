"""Parte 3 de punta a punta: aprobación humana por departamento, arbitraje y documento final.

Ruta E2E reproducible: el ticket recorre las Partes 1 y 2 con el grafo real (agentes falsos de
`test_rfp_intake_flow.py` y `test_rfp_response_flow.py`), en una base SQLite temporal con el checkpointer SQLite en el
mismo archivo, y las aprobaciones de cada responsable se simulan con `approval_runner.submit_decision`, que es el
mismo `resume` programático que ejecuta la tarea `rfp_intake.resume_approval` del worker. Sin gateway ni Redis.

Luna Cosmetics (US/USD) activa `warehouse` y `lastmile`: A = Warehouse (Ana Whitfield), B = Last Mile (Carlos Vega).
"""

import pytest
from pydantic import ValidationError
from sqlmodel import Session, select

from data.pipelines.rfp_intake import approval_runner, checkpoints, response_runner, runner
from data.pipelines.rfp_intake.approval import InvalidDecisionError
from data.pipelines.rfp_intake.schema import RfpFinalDocument
from services.tasks import rfp_intake as rfp_tasks
from tests.pipelines.test_rfp_intake_flow import RFP_LINES, engine, fake_agents, minimal_pdf  # noqa: F401
from tests.pipelines.test_rfp_response_flow import analyzed_ticket, part2_agents, section_draft  # noqa: F401

VOLUME_LINE = "**Volumen asumido:** 5.000 pedidos/mes"


def with_fact(draft: str, line: str) -> str:
    """Añade la línea de hechos bajo la cabecera, como pide el prompt del generador."""
    head, rest = draft.split("\n", 1)
    return f"{head}\n{line}\n{rest}"


def decide(engine, ticket_id, department, decision="approve", **fields):  # noqa: F811
    review = approval_runner.pending_reviews(engine, ticket_id)[department]
    payload = {"decision": decision, "review_round": review["review_round"], "decided_by": "ventas@trackflow.com"}
    return approval_runner.submit_decision(engine, ticket_id, department, {**payload, **fields})


def sections_of(engine, ticket_id):  # noqa: F811
    return {s.department_id: s for s in runner.get_ticket_detail(engine, ticket_id).sections}


def trace_nodes(engine, ticket_id, part="parte_3"):  # noqa: F811
    return [e["node"] for e in runner.get_ticket_detail(engine, ticket_id).ticket.trace if e["part"] == part]


def generator_calls(calls, department):
    return [c for c in calls if c["agent"] == f"{department}_generator"]


@pytest.fixture
def evaluated_ticket(engine, analyzed_ticket, part2_agents):  # noqa: F811
    """Ticket de Luna al final de la Parte 2 (`en_evaluación` con `response_handoff`)."""
    assert response_runner.generate_responses(engine, analyzed_ticket, max_iterations=2) == "en_evaluación"
    return analyzed_ticket


def test_an_rfp_goes_from_upload_to_final_document_with_one_approval_per_department(
    engine, evaluated_ticket, part2_agents  # noqa: F811
):
    ticket_id = evaluated_ticket

    assert approval_runner.start_approval(engine, ticket_id, max_rounds=3) == "esperando_aprobación"

    pending = approval_runner.pending_reviews(engine, ticket_id)
    assert set(pending) == {"warehouse", "lastmile"}
    assert pending["warehouse"]["approver"] == "Ana Whitfield" and pending["lastmile"]["approver"] == "Carlos Vega"
    assert pending["warehouse"]["review_round"] == 1 and pending["warehouse"]["evaluation_pass"] is True
    assert {s.approval_status for s in sections_of(engine, ticket_id).values()} == {"pendiente"}

    assert decide(engine, ticket_id, "warehouse") == "esperando_aprobación"
    assert list(approval_runner.pending_reviews(engine, ticket_id)) == ["lastmile"]
    assert decide(engine, ticket_id, "lastmile") == "terminado"

    detail = runner.get_ticket_detail(engine, ticket_id)
    assert approval_runner.pending_reviews(engine, ticket_id) == {}
    for section in detail.sections:
        assert section.approval_status == "aprobada" and section.approved_at is not None
    assert {s.department_id: s.approver for s in detail.sections} == {
        "warehouse": "Ana Whitfield",
        "lastmile": "Carlos Vega",
    }
    document = detail.final_document
    assert document.currency == "USD" and document.rfp_id == detail.ticket.rfp_id
    assert [s["department_id"] for s in document.sections] == ["warehouse", "lastmile"]
    assert document.content.startswith("# Propuesta económica de TrackFlow para Luna Cosmetics")
    # El texto aprobado entra sin reescribir.
    assert detail.sections[0].draft_content.strip() in document.content
    assert "| Warehouse Operations | Ana Whitfield |" in document.content
    # Trazabilidad de punta a punta, en orden: Parte 1 → Parte 2 → Parte 3, con agente, entrada, salida y timestamp.
    trace = detail.ticket.trace
    parts = [entry["part"] for entry in trace]
    assert parts == sorted(parts) and {"parte_1", "parte_2", "parte_3"} <= set(parts)
    assert [entry["timestamp"] for entry in trace] == sorted(entry["timestamp"] for entry in trace)
    assert all({"agent", "input", "output", "timestamp", "node"} <= set(entry) for entry in trace)
    nodes = trace_nodes(engine, ticket_id)
    assert nodes[0] == "check_conflicts" and nodes[-1] == "finalize_document"
    human = [e for e in trace if e["node"].endswith("_human_review")]
    assert [(e["agent"], e["output"]["decision"]["decision"]) for e in human] == [
        ("Ana Whitfield", "approve"),
        ("Carlos Vega", "approve"),
    ]


def test_b_is_approved_while_a_is_still_interrupted(engine, evaluated_ticket, part2_agents):  # noqa: F811
    drafts, calls, _ = part2_agents
    drafts["lastmile"].append(section_draft("Last Mile and Carrier Management", extra="\nCobertura revisada.\n"))
    ticket_id = evaluated_ticket
    approval_runner.start_approval(engine, ticket_id, max_rounds=3)
    warehouse_interrupt = approval_runner.pending_reviews(engine, ticket_id)["warehouse"]["interrupt_id"]
    lastmile_calls_before = len(generator_calls(calls, "lastmile"))

    # B pide cambios: su rama vuelve al generador de la Parte 2, se reevalúa y vuelve a revisión, con A en pausa.
    decide(engine, ticket_id, "lastmile", "request_changes", comment="Añade la cobertura por estado en EE. UU.")
    pending = approval_runner.pending_reviews(engine, ticket_id)
    assert pending["lastmile"]["review_round"] == 2 and pending["lastmile"]["revisions"] == 1
    assert pending["warehouse"]["interrupt_id"] == warehouse_interrupt
    retry_prompt = generator_calls(calls, "lastmile")[-1]["user"]
    assert len(generator_calls(calls, "lastmile")) == lastmile_calls_before + 1
    assert "Petición de cambios de Carlos Vega" in retry_prompt and "cobertura por estado" in retry_prompt

    # B se aprueba en su segunda revisión; A sigue interrumpido con la misma interrupción.
    assert decide(engine, ticket_id, "lastmile") == "esperando_aprobación"
    sections = sections_of(engine, ticket_id)
    assert sections["lastmile"].approval_status == "aprobada" and sections["lastmile"].review_round == 2
    assert "Cobertura revisada." in sections["lastmile"].draft_content
    assert sections["warehouse"].approval_status == "pendiente"
    assert approval_runner.pending_reviews(engine, ticket_id)["warehouse"]["interrupt_id"] == warehouse_interrupt
    nodes = trace_nodes(engine, ticket_id)
    assert nodes.count("lastmile_record_decision") == 2 and "warehouse_record_decision" not in nodes
    assert runner.get_ticket_detail(engine, ticket_id).final_document is None

    assert decide(engine, ticket_id, "warehouse") == "terminado"


def test_resume_continues_from_the_checkpoint_in_another_process(engine, evaluated_ticket, part2_agents):  # noqa: F811
    _, calls, _ = part2_agents
    ticket_id = evaluated_ticket
    approval_runner.start_approval(engine, ticket_id, max_rounds=3)
    calls.clear()
    # Otro proceso del worker: grafo y checkpointer nuevos sobre el mismo archivo.
    approval_runner._graphs.clear()
    checkpoints._checkpointer.cache_clear()

    decide(engine, ticket_id, "warehouse")
    decide(engine, ticket_id, "lastmile")

    assert approval_runner.ticket_status(engine, ticket_id) == "terminado"
    # No se repitió nada de lo terminado: ni generadores ni evaluadores, y el inicio corrió una sola vez.
    assert calls == []
    nodes = trace_nodes(engine, ticket_id)
    assert nodes.count("check_conflicts") == 2  # al empezar y al converger las ramas
    assert nodes.count("warehouse_request_review") == 1 and nodes.count("lastmile_request_review") == 1


@pytest.fixture
def second_analyzed_ticket(engine, fake_agents):  # noqa: F811
    ticket = runner.receive_upload(engine, content=minimal_pdf(RFP_LINES), filename="luna-2.pdf", uploaded_by="u")
    assert runner.process_ticket(engine, ticket.ticket_id) == "analisis_completo"
    return ticket.ticket_id


def test_concurrent_tickets_never_share_a_checkpoint(
    engine, analyzed_ticket, second_analyzed_ticket, part2_agents  # noqa: F811
):
    first, second = analyzed_ticket, second_analyzed_ticket
    for ticket_id in (first, second):
        response_runner.generate_responses(engine, ticket_id, max_iterations=2)
        approval_runner.start_approval(engine, ticket_id, max_rounds=3)

    decide(engine, first, "warehouse")
    decide(engine, first, "lastmile")

    assert checkpoints.thread_id_for(first) == f"rfp-{first}" != checkpoints.thread_id_for(second)
    assert approval_runner.ticket_status(engine, first) == "terminado"
    assert approval_runner.ticket_status(engine, second) == "esperando_aprobación"
    assert set(approval_runner.pending_reviews(engine, second)) == {"warehouse", "lastmile"}


def test_invalid_decisions_never_reach_the_graph(engine, evaluated_ticket):  # noqa: F811
    ticket_id = evaluated_ticket
    approval_runner.start_approval(engine, ticket_id, max_rounds=3)
    before = approval_runner.pending_reviews(engine, ticket_id)
    base = {"review_round": 1, "decided_by": "ventas@trackflow.com"}

    with pytest.raises(ValidationError):
        approval_runner.submit_decision(engine, ticket_id, "warehouse", {**base, "decision": "request_changes"})
    with pytest.raises(ValidationError):
        approval_runner.submit_decision(engine, ticket_id, "warehouse", {**base, "decision": "maybe"})
    with pytest.raises(InvalidDecisionError, match="revisión 1"):
        stale = {**base, "decision": "approve", "review_round": 2}
        approval_runner.submit_decision(engine, ticket_id, "warehouse", stale)
    with pytest.raises(InvalidDecisionError, match="Warehouse"):
        approval_runner.submit_decision(
            engine, ticket_id, "lastmile", {**base, "decision": "approve", "committed_monthly_capacity": 4000}
        )
    with pytest.raises(approval_runner.NoPendingReviewError):
        approval_runner.submit_decision(engine, ticket_id, "reverse", {**base, "decision": "approve"})

    assert approval_runner.pending_reviews(engine, ticket_id) == before
    assert "warehouse_record_decision" not in trace_nodes(engine, ticket_id)


def test_the_revision_limit_only_allows_approve_or_reject(engine, evaluated_ticket):  # noqa: F811
    ticket_id = evaluated_ticket
    approval_runner.start_approval(engine, ticket_id, max_rounds=1)
    assert approval_runner.pending_reviews(engine, ticket_id)["lastmile"]["allowed_decisions"] == [
        "approve",
        "request_changes",
        "reject",
    ]

    decide(engine, ticket_id, "lastmile", "request_changes", comment="Detalla el SLA express por destino.")

    review = approval_runner.pending_reviews(engine, ticket_id)["lastmile"]
    assert review["revisions"] == 1 and review["allowed_decisions"] == ["approve", "reject"]
    with pytest.raises(InvalidDecisionError, match="agotó las 1 revisiones"):
        decide(engine, ticket_id, "lastmile", "request_changes", comment="Otra vuelta más, por favor.")
    assert approval_runner.pending_reviews(engine, ticket_id)["lastmile"]["review_round"] == 2


def test_a_rejected_section_closes_part_3_without_final_document(engine, evaluated_ticket):  # noqa: F811
    ticket_id = evaluated_ticket
    approval_runner.start_approval(engine, ticket_id, max_rounds=3)

    decide(engine, ticket_id, "lastmile", "reject", comment="El cliente usará su propio transportista.")
    decide(engine, ticket_id, "warehouse")

    detail = runner.get_ticket_detail(engine, ticket_id)
    assert detail.ticket.status == "esperando_aprobación" and detail.final_document is None
    assert sections_of(engine, ticket_id)["lastmile"].approval_status == "rechazada"
    assert trace_nodes(engine, ticket_id)[-1] == "close_without_document"
    assert approval_runner.pending_reviews(engine, ticket_id) == {}


def test_currency_mismatch_is_arbitrated_by_miguel_torres_before_the_review(
    engine, analyzed_ticket, part2_agents  # noqa: F811
):
    drafts, calls, _ = part2_agents
    # Last Mile cotiza en EUR para un cliente de EE. UU.; tras la instrucción del árbitro corrige a USD.
    drafts["lastmile"] = [
        section_draft("Last Mile and Carrier Management", currency="EUR"),
        section_draft("Last Mile and Carrier Management", currency="EUR"),
        section_draft("Last Mile and Carrier Management"),
    ]
    response_runner.generate_responses(engine, analyzed_ticket, max_iterations=2)
    ticket_id = analyzed_ticket

    approval_runner.start_approval(engine, ticket_id, max_rounds=3)

    ticket = runner.get_ticket_detail(engine, ticket_id).ticket
    [record] = ticket.arbitrations
    assert record["trigger_id"] == "currency-mismatch" and record["arbiter"] == "Miguel Torres"
    assert record["department_id"] == "lastmile" and record["action"] == "request_changes"
    assert "lastmile: EUR" in record["evidence"]
    assert "Arbitraje currency-mismatch (Miguel Torres)" in generator_calls(calls, "lastmile")[-1]["user"]
    review = approval_runner.pending_reviews(engine, ticket_id)["lastmile"]
    assert review["revisions"] == 1 and any("currency-mismatch" in note for note in review["arbitration_notes"])
    assert "**Moneda:** USD" in sections_of(engine, ticket_id)["lastmile"].draft_content
    assert trace_nodes(engine, ticket_id)[:2] == ["check_conflicts", "arbitrate"]

    decide(engine, ticket_id, "warehouse")
    assert decide(engine, ticket_id, "lastmile") == "terminado"


def test_an_unresolved_conflict_is_rejected_when_the_arbitration_limit_is_reached(
    engine, analyzed_ticket, part2_agents  # noqa: F811
):
    drafts, _, _ = part2_agents
    drafts["lastmile"] = [section_draft("Last Mile and Carrier Management", currency="EUR")]  # nunca lo corrige
    response_runner.generate_responses(engine, analyzed_ticket, max_iterations=1)
    ticket_id = analyzed_ticket

    approval_runner.start_approval(engine, ticket_id, max_rounds=1)
    decide(engine, ticket_id, "warehouse")
    decide(engine, ticket_id, "lastmile")

    detail = runner.get_ticket_detail(engine, ticket_id)
    assert [(r["round"], r["action"]) for r in detail.ticket.arbitrations] == [(1, "request_changes"), (2, "reject")]
    assert sections_of(engine, ticket_id)["lastmile"].approval_status == "rechazada"
    assert detail.final_document is None and detail.ticket.status == "esperando_aprobación"
    assert trace_nodes(engine, ticket_id)[-2:] == ["arbitrate", "close_without_document"]


def test_volume_above_warehouse_capacity_sends_last_mile_back_and_keeps_warehouse_approved(
    engine, analyzed_ticket, part2_agents  # noqa: F811
):
    drafts, calls, _ = part2_agents
    drafts["lastmile"] = [
        with_fact(section_draft("Last Mile and Carrier Management"), VOLUME_LINE),
        with_fact(section_draft("Last Mile and Carrier Management"), "**Volumen asumido:** 3.000 pedidos/mes"),
    ]
    response_runner.generate_responses(engine, analyzed_ticket, max_iterations=2)
    ticket_id = analyzed_ticket
    approval_runner.start_approval(engine, ticket_id, max_rounds=3)

    # Ana Whitfield compromete 3.000 pedidos/mes al aprobar; Last Mile asumía 5.000.
    decide(engine, ticket_id, "warehouse", committed_monthly_capacity=3000)
    decide(engine, ticket_id, "lastmile")

    [record] = runner.get_ticket_detail(engine, ticket_id).ticket.arbitrations
    assert record["trigger_id"] == "volume-vs-capacity" and record["arbiter"] == "Miguel Torres"
    assert record["department_id"] == "lastmile"
    assert "3000 pedidos/mes" in generator_calls(calls, "lastmile")[-1]["user"]
    pending = approval_runner.pending_reviews(engine, ticket_id)
    assert list(pending) == ["lastmile"] and pending["lastmile"]["review_round"] == 2
    warehouse = sections_of(engine, ticket_id)["warehouse"]
    assert warehouse.approval_status == "aprobada"
    assert "**Capacidad comprometida:** 3.000 pedidos/mes" in warehouse.draft_content

    assert decide(engine, ticket_id, "lastmile") == "terminado"
    assert "3.000 pedidos/mes" in runner.get_ticket_detail(engine, ticket_id).final_document.content


def test_part_3_does_not_start_twice_or_before_part_2(engine, analyzed_ticket, evaluated_ticket):  # noqa: F811
    approval_runner.start_approval(engine, evaluated_ticket, max_rounds=3)
    pending = approval_runner.pending_reviews(engine, evaluated_ticket)

    assert approval_runner.start_approval(engine, evaluated_ticket, max_rounds=3) == "esperando_aprobación"
    assert approval_runner.pending_reviews(engine, evaluated_ticket) == pending
    assert trace_nodes(engine, evaluated_ticket).count("check_conflicts") == 1


def test_part_3_skips_a_ticket_without_the_part_2_handoff(engine, analyzed_ticket):  # noqa: F811
    assert approval_runner.start_approval(engine, analyzed_ticket, max_rounds=3) == "analisis_completo"
    assert approval_runner.pending_reviews(engine, analyzed_ticket) == {}


def test_the_part_2_task_enqueues_part_3(monkeypatch):
    queued: list[list[str]] = []
    monkeypatch.setattr(rfp_tasks, "intake_engine", lambda: None)
    monkeypatch.setattr(rfp_tasks, "generate_responses", lambda engine, ticket_id: "needs_human_review")
    monkeypatch.setattr(rfp_tasks.start_approval_task, "apply_async", lambda args, retry: queued.append(args))

    rfp_tasks.generate_rfp_responses_task.apply(args=["ticket-1"]).get()

    assert queued == [["ticket-1"]]


def test_a_repeated_decision_is_ignored_by_the_resume_task(engine, evaluated_ticket, monkeypatch):  # noqa: F811
    ticket_id = evaluated_ticket
    approval_runner.start_approval(engine, ticket_id, max_rounds=3)
    monkeypatch.setattr(rfp_tasks, "intake_engine", lambda: engine)
    decision = {"decision": "approve", "review_round": 1, "decided_by": "ventas@trackflow.com"}

    first = rfp_tasks.resume_approval_task.apply(args=[ticket_id, "warehouse", decision]).get()
    second = rfp_tasks.resume_approval_task.apply(args=[ticket_id, "warehouse", decision]).get()

    assert first["status"] == "esperando_aprobación"
    assert second["status"] == "ignored"
    with Session(engine) as session:
        assert session.exec(select(RfpFinalDocument)).first() is None
    assert trace_nodes(engine, ticket_id).count("warehouse_record_decision") == 1
