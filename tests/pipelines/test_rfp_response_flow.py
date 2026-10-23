"""Parte 2 de punta a punta sobre el ticket de la Parte 1, en una base SQLite temporal y sin gateway LLM.

El ticket llega a `analisis_completo` con el grafo real de la Parte 1 (agentes falsos de
`test_rfp_intake_flow.py`). Después, los generadores y evaluadores falsos responden según el departamento y la
iteración, para recorrer el ciclo generador-evaluador: éxito a la primera, reintento con feedback y límite agotado.
"""

import threading

import pytest
from sqlmodel import Session

from data.pipelines.rfp_intake import generators, llm, response_runner, runner
from data.pipelines.rfp_intake.schema import RfpTicket
from services.tasks import rfp_intake as rfp_tasks
from tests.pipelines.test_rfp_intake_flow import RFP_LINES, engine, fake_agents, minimal_pdf  # noqa: F401
from tests.pipelines.test_rfp_response_agents import reverse_draft


def section_draft(department: str, currency: str = "USD", extra: str = "") -> str:
    """Borrador que cumple los lineamientos (el de Reverse adaptado al departamento y la moneda)."""
    draft = reverse_draft().replace("EUR", currency).replace("Reverse Logistics", department)
    return draft + extra


CARRIER_RATE_LINE = "\nEl envío estándar con UPS nos cuesta 4,10 USD por paquete.\n"


@pytest.fixture
def analyzed_ticket(engine, fake_agents):  # noqa: F811
    """Ticket de Luna Cosmetics (US/USD, `warehouse` + `lastmile`) en `analisis_completo` con su handoff."""
    ticket = runner.receive_upload(engine, content=minimal_pdf(RFP_LINES), filename="luna.pdf", uploaded_by="user-1")
    assert runner.process_ticket(engine, ticket.ticket_id) == "analisis_completo"
    fake_agents.clear()
    return ticket.ticket_id


@pytest.fixture
def part2_agents(monkeypatch, engine):  # noqa: F811
    """Generadores y evaluadores falsos. `drafts[dept]` es la lista de borradores por iteración (el último se repite)."""
    drafts: dict[str, list[str]] = {
        "warehouse": [section_draft("Warehouse Operations")],
        "lastmile": [section_draft("Last Mile and Carrier Management")],
    }
    calls: list[dict] = []
    statuses_seen: dict[str, list[str]] = {}
    lock = threading.Lock()

    def ticket_status(ticket_id: str) -> str:
        with Session(engine) as session:
            return session.get(RfpTicket, ticket_id).status

    def ask_json(agent, system_prompt, user_prompt, schema):
        department = agent.split("_")[0]
        with lock:
            calls.append({"agent": agent, "user": user_prompt})
            iteration = sum(1 for c in calls if c["agent"] == f"{department}_generator")
        if agent.endswith("_generator"):
            options = drafts[department]
            return schema.model_validate({"content": options[min(iteration, len(options)) - 1]})
        if agent.endswith("_relevance_evaluator"):
            return schema.model_validate({"missing_aspect_ids": []})
        return schema.model_validate({"violations": []})

    monkeypatch.setattr(llm, "ask_json", ask_json)
    monkeypatch.setattr(generators, "retrieve_knowledge", lambda department_id: ["[kb] SLA del 90% mensual."])

    original_update = response_runner.DatabaseProgress.section_update

    def spying_update(self, department_id, **fields):
        original_update(self, department_id, **fields)
        if "draft_status" in fields:
            statuses_seen.setdefault("ticket", []).append(ticket_status(self.ticket_id))

    monkeypatch.setattr(response_runner.DatabaseProgress, "section_update", spying_update)
    return drafts, calls, statuses_seen


def generator_prompts(calls: list[dict], department: str) -> list[str]:
    return [c["user"] for c in calls if c["agent"] == f"{department}_generator"]


def test_sections_that_pass_first_time_leave_the_handoff_ready_for_part_3(engine, analyzed_ticket, part2_agents):
    _, calls, statuses_seen = part2_agents

    status = response_runner.generate_responses(engine, analyzed_ticket, max_iterations=3)

    assert status == "en_evaluación"
    detail = runner.get_ticket_detail(engine, analyzed_ticket)
    assert detail.ticket.generation_attempts == 1 and detail.ticket.last_error is None
    for section in detail.sections:
        assert section.draft_status == "evaluacion_superada"
        assert section.iterations == 1 and len(section.evaluation_history) == 1
        assert section.draft_content.startswith("## ")
        assert section.evaluation_results["overall_pass"] is True
        assert section.evaluation_results["section_id"] == f"{analyzed_ticket}:{section.department_id}"
    handoff = detail.ticket.response_handoff
    assert handoff["version"] == "rfp_intake.response_handoff.v1"
    assert handoff["currency"] == "USD" and handoff["needs_human_review"] == []
    assert [s["department_id"] for s in handoff["sections"]] == ["warehouse", "lastmile"]
    assert all(s["evaluation_result"]["overall_pass"] for s in handoff["sections"])
    # El ticket pasó por las dos etapas de la Parte 2 mientras corría el grafo.
    assert statuses_seen["ticket"][0] == "generando_borrador"
    assert "en_evaluación" in statuses_seen["ticket"]
    # Tres evaluadores por sección y ninguna lectura del PDF: los generadores solo ven el handoff.
    assert sorted(c["agent"] for c in calls if c["agent"].startswith("warehouse_")) == [
        "warehouse_compliance_evaluator",
        "warehouse_generator",
        "warehouse_relevance_evaluator",
    ]
    prompt = generator_prompts(calls, "warehouse")[0]
    assert "5,000 pedidos al mes" in prompt
    assert "Could you send over a proposal" not in prompt


def test_a_failed_section_goes_back_to_its_generator_with_the_feedback(engine, analyzed_ticket, part2_agents):
    drafts, calls, _ = part2_agents
    drafts["lastmile"] = [
        section_draft("Last Mile and Carrier Management", extra=CARRIER_RATE_LINE),
        section_draft("Last Mile and Carrier Management"),
    ]

    assert response_runner.generate_responses(engine, analyzed_ticket, max_iterations=3) == "en_evaluación"

    sections = {s.department_id: s for s in runner.get_ticket_detail(engine, analyzed_ticket).sections}
    lastmile = sections["lastmile"]
    assert lastmile.draft_status == "evaluacion_superada" and lastmile.iterations == 2
    first, second = lastmile.evaluation_history
    assert first["evaluation"]["compliance"]["rule_ids"] == ["no-carrier-rates"]
    assert "[no-carrier-rates]" in first["evaluation"]["feedback_for_generator"]
    assert second["evaluation"]["overall_pass"] is True
    retry_prompt = generator_prompts(calls, "lastmile")[1]
    assert "4,10 USD" in retry_prompt and "[no-carrier-rates]" in retry_prompt
    # El reintento de Last Mile no hace iterar a Warehouse: cada departamento tiene su propio ciclo.
    assert sections["warehouse"].iterations == 1


def test_a_section_that_exhausts_the_limit_is_kept_as_needs_human_review(engine, analyzed_ticket, part2_agents):
    drafts, calls, _ = part2_agents
    drafts["warehouse"] = [section_draft("Warehouse Operations", currency="EUR")]  # Luna es de EE. UU. → USD

    status = response_runner.generate_responses(engine, analyzed_ticket, max_iterations=2)

    assert status == "needs_human_review"
    assert len(generator_prompts(calls, "warehouse")) == 2
    detail = runner.get_ticket_detail(engine, analyzed_ticket)
    sections = {s.department_id: s for s in detail.sections}
    warehouse = sections["warehouse"]
    assert warehouse.draft_status == "needs_human_review" and warehouse.iterations == 2
    assert warehouse.draft_content == drafts["warehouse"][0].strip()
    assert warehouse.evaluation_results["overall_pass"] is False
    assert warehouse.evaluation_results["compliance"]["rule_ids"] == ["currency-by-country"]
    assert sections["lastmile"].draft_status == "evaluacion_superada"
    handoff = detail.ticket.response_handoff
    assert handoff["status"] == "needs_human_review" and handoff["needs_human_review"] == ["warehouse"]
    flagged = handoff["sections"][0]
    assert flagged["needs_human_review"] is True
    assert flagged["draft_content"] == warehouse.draft_content
    assert flagged["evaluation_result"] == warehouse.evaluation_results


def test_a_ticket_with_its_part_3_handoff_is_not_generated_twice(engine, analyzed_ticket, part2_agents):
    _, calls, _ = part2_agents
    response_runner.generate_responses(engine, analyzed_ticket, max_iterations=3)
    calls.clear()

    assert response_runner.generate_responses(engine, analyzed_ticket, max_iterations=3) == "en_evaluación"
    assert calls == []


def test_part_2_only_starts_from_the_routing_handoff(engine, fake_agents, part2_agents):  # noqa: F811
    _, calls, _ = part2_agents
    ticket = runner.receive_upload(engine, content=minimal_pdf(RFP_LINES), filename="luna.pdf", uploaded_by="user-1")

    assert response_runner.generate_responses(engine, ticket.ticket_id) == "analizando"
    assert calls == []


def test_a_generator_failure_keeps_the_ticket_and_records_the_error(engine, analyzed_ticket, monkeypatch, part2_agents):
    def gateway_down(*args, **kwargs):
        raise llm.RfpAgentError("El agente warehouse_generator no pudo llamar al modelo (APIConnectionError).")

    monkeypatch.setattr(generators, "generate", gateway_down)

    with pytest.raises(llm.RfpAgentError):
        response_runner.generate_responses(engine, analyzed_ticket, max_iterations=3)

    ticket = runner.get_ticket_detail(engine, analyzed_ticket).ticket
    assert ticket.status == "generando_borrador" and ticket.response_handoff is None
    assert ticket.last_error.startswith("RfpAgentError: El agente warehouse_generator")


def test_the_part_1_task_enqueues_part_2_when_the_analysis_is_complete(monkeypatch):
    queued: list[list[str]] = []
    monkeypatch.setattr(rfp_tasks, "intake_engine", lambda: None)
    monkeypatch.setattr(rfp_tasks, "process_ticket", lambda engine, ticket_id: "analisis_completo")
    monkeypatch.setattr(
        rfp_tasks.generate_rfp_responses_task, "apply_async", lambda args, retry: queued.append(args)
    )

    result = rfp_tasks.process_rfp_ticket_task.apply(args=["ticket-1"]).get()

    assert result["status"] == "analisis_completo"
    assert queued == [["ticket-1"]]


def test_the_part_1_task_does_not_enqueue_part_2_for_a_discarded_document(monkeypatch):
    queued: list[list[str]] = []
    monkeypatch.setattr(rfp_tasks, "intake_engine", lambda: None)
    monkeypatch.setattr(rfp_tasks, "process_ticket", lambda engine, ticket_id: "descartado")
    monkeypatch.setattr(
        rfp_tasks.generate_rfp_responses_task, "apply_async", lambda args, retry: queued.append(args)
    )

    rfp_tasks.process_rfp_ticket_task.apply(args=["ticket-2"]).get()

    assert queued == []
