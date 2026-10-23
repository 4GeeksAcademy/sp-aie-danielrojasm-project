"""Piezas de la Parte 3 sin grafo: triggers del BRIEFING §7, árbitro, decisión humana, documento final y traza."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from data.pipelines.rfp_intake import approval, conflicts, final_document, tracing
from tests.pipelines.test_rfp_response_agents import reverse_draft


def facts(**drafts: str) -> dict[str, conflicts.SectionFacts]:
    return {department_id: conflicts.extract_facts(department_id, draft) for department_id, draft in drafts.items()}


WAREHOUSE_HEADER = "## Warehouse Operations — Propuesta económica\n**Responsable:** Ana Whitfield · **Moneda:** USD"
LASTMILE_HEADER = "## Last Mile and Carrier Management — Propuesta económica\n**Responsable:** Carlos Vega · **Moneda:** USD"


def warehouse_draft(line: str = "**Capacidad comprometida:** 4.000 pedidos/mes") -> str:
    return f"{WAREHOUSE_HEADER}\n{line}\n"


def lastmile_draft(
    line: str = "**Volumen asumido:** 5,000 pedidos/mes", amounts: str = "| Envío | 6,90 USD | paquete |"
) -> str:
    return f"{LASTMILE_HEADER}\n{line}\n{amounts}\n"


# --- Hechos estructurados ----------------------------------------------------------------------


def test_facts_are_read_from_the_fixed_lines_and_the_quoted_amounts():
    extracted = facts(warehouse=warehouse_draft(), lastmile=lastmile_draft())

    assert extracted["warehouse"].monthly_capacity == 4000
    assert extracted["lastmile"].assumed_monthly_volume == 5000
    assert extracted["lastmile"].currencies == ["USD"]


def test_a_capacity_still_to_confirm_is_not_a_number():
    extracted = conflicts.extract_facts("warehouse", warehouse_draft("**Capacidad comprometida:** a confirmar con Ana"))

    assert extracted.monthly_capacity is None


def test_the_capacity_committed_by_ana_overrides_the_draft():
    assert conflicts.extract_facts("warehouse", warehouse_draft(), committed_capacity=2500).monthly_capacity == 2500


def test_the_capacity_ana_commits_is_written_into_her_section():
    replaced = conflicts.with_committed_capacity(warehouse_draft(), 2500)
    inserted = conflicts.with_committed_capacity(WAREHOUSE_HEADER + "\n### Alcance\n", 12000)

    assert "**Capacidad comprometida:** 2.500 pedidos/mes" in replaced and "4.000" not in replaced
    assert inserted.splitlines()[2] == "**Capacidad comprometida:** 12.000 pedidos/mes"
    assert conflicts.extract_facts("warehouse", replaced).monthly_capacity == 2500


def test_a_word_mentioning_another_currency_is_not_a_quote():
    draft = lastmile_draft(amounts="Los precios no incluyen conversión a euros.")

    assert conflicts.extract_facts("lastmile", draft).currencies == ["USD"]


# --- Triggers y árbitro fijo -------------------------------------------------------------------


def test_volume_above_capacity_is_arbitrated_by_miguel_torres_and_sends_only_lastmile_back():
    [conflict] = conflicts.detect(facts(warehouse=warehouse_draft(), lastmile=lastmile_draft()), "USD")

    assert conflict.trigger_id == "volume-vs-capacity" and conflict.arbiter == "Miguel Torres"
    assert list(conflict.instructions) == ["lastmile"]
    assert "4000 pedidos/mes" in conflict.instructions["lastmile"]


def test_volume_within_capacity_or_unknown_is_not_a_conflict():
    within = lastmile_draft("**Volumen asumido:** 3.000 pedidos/mes")
    assert conflicts.detect(facts(warehouse=warehouse_draft(), lastmile=within), "USD") == []
    assert conflicts.detect(facts(warehouse=warehouse_draft("a confirmar"), lastmile=lastmile_draft()), "USD") == []


def test_returns_under_48h_are_arbitrated_by_sofia_in_reverse_and_by_miguel_elsewhere():
    promise = "\nLas devoluciones se procesan en 24 horas.\n"
    detected = conflicts.detect(
        facts(warehouse=warehouse_draft() + promise, reverse=reverse_draft(processing="en 24 horas")), "EUR"
    )
    returns = {c.arbiter: c for c in detected if c.trigger_id == "returns-sla-breach"}

    assert set(returns) == {"Sofía Ramos", "Miguel Torres"}
    assert list(returns["Sofía Ramos"].instructions) == ["reverse"]
    assert list(returns["Miguel Torres"].instructions) == ["warehouse"]
    assert "48 horas" in returns["Sofía Ramos"].instructions["reverse"]


def test_a_section_quoting_another_currency_than_the_country_must_be_rewritten():
    draft = lastmile_draft(line="", amounts="| Envío | 6,90 EUR | paquete |")

    [conflict] = conflicts.detect(facts(lastmile=draft, reverse=reverse_draft().replace("EUR", "USD")), "USD")

    assert conflict.trigger_id == "currency-mismatch" and conflict.arbiter == "Miguel Torres"
    assert list(conflict.instructions) == ["lastmile"]
    assert "USD" in conflict.instructions["lastmile"] and "EUR" in conflict.instructions["lastmile"]


def test_two_sections_with_different_currencies_conflict_even_without_country():
    [conflict] = conflicts.detect(facts(lastmile=lastmile_draft(), reverse=reverse_draft()), None)

    assert conflict.trigger_id == "currency-mismatch" and set(conflict.instructions) == {"lastmile", "reverse"}


def test_consistent_sections_have_no_conflict():
    assert conflicts.detect(facts(reverse=reverse_draft()), "EUR") == []


# --- Decisión humana ---------------------------------------------------------------------------


REVIEW = {"department_id": "lastmile", "review_round": 2, "max_rounds": 3, "allowed_decisions": ["approve", "reject"]}


def decision(**fields):
    base = {"decision": "approve", "review_round": 2, "decided_by": "u"}
    return approval.ApprovalDecision.model_validate({**base, **fields})


def test_changes_and_rejections_need_a_reason():
    with pytest.raises(ValidationError, match="motivo"):
        decision(decision="reject", comment="no")
    assert decision(decision="reject", comment="  Precio fuera de mercado.  ").comment == "Precio fuera de mercado."


def test_unknown_fields_and_decisions_are_rejected():
    with pytest.raises(ValidationError):
        decision(decision="escalate")
    with pytest.raises(ValidationError):
        decision(approver="Otra persona")


def test_a_decision_is_checked_against_the_pending_review():
    approval.check_against(decision(), REVIEW)
    with pytest.raises(approval.InvalidDecisionError, match="revisión 2"):
        approval.check_against(decision(review_round=1), REVIEW)
    with pytest.raises(approval.InvalidDecisionError, match="agotó"):
        approval.check_against(decision(decision="request_changes", comment="Cambia el SLA express."), REVIEW)
    with pytest.raises(approval.InvalidDecisionError, match="Warehouse"):
        approval.check_against(decision(committed_monthly_capacity=1000), REVIEW)


def test_request_changes_is_only_offered_while_revisions_remain():
    assert approval.allowed_decisions(revisions=2, max_rounds=3) == ["approve", "request_changes", "reject"]
    assert approval.allowed_decisions(revisions=3, max_rounds=3) == ["approve", "reject"]


# --- Documento final ---------------------------------------------------------------------------


SHARED = {
    "client_name": "ModaViva",
    "client_country": "ES",
    "currency": "EUR",
    "services_requested": ["warehousing", "reverse_logistics"],
    "monthly_volume": None,
    "deadline": "2026-11-30",
}


def approved(department_id: str, content: str, status: str = "aprobada") -> dict:
    return {
        "department_id": department_id,
        "approval_status": status,
        "approver": {"warehouse": "Ana Whitfield", "reverse": "Sofía Ramos"}[department_id],
        "approved_at": "2026-10-20T10:00:00+00:00",
        "review_round": 1,
        "draft_content": content,
    }


def test_the_final_document_consolidates_the_approved_text_in_briefing_order():
    document = final_document.build(
        "t-1",
        "r-1",
        SHARED,
        [approved("reverse", reverse_draft()), approved("warehouse", warehouse_draft())],
        datetime(2026, 10, 21, tzinfo=timezone.utc),
    )

    assert document["currency"] == "EUR"
    assert [s["department_id"] for s in document["sections"]] == ["warehouse", "reverse"]
    content = document["content"]
    assert content.startswith("# Propuesta económica de TrackFlow para ModaViva")
    assert "| País de operación | España |" in content
    assert "| Volumen mensual de referencia | A confirmar |" in content
    assert "| Fecha límite de la RFP | 30 de noviembre de 2026 |" in content
    assert "| Reverse Logistics | Sofía Ramos | 20 de octubre de 2026 | 1 |" in content
    assert reverse_draft().strip() in content
    assert content.index("## Warehouse Operations") < content.index("## Reverse Logistics")


def test_the_final_document_requires_every_section_approved():
    with pytest.raises(ValueError, match="aprobadas"):
        pending = approved("warehouse", warehouse_draft(), status="pendiente")
        final_document.build("t-1", None, SHARED, [pending], datetime.now(timezone.utc))


# --- Traza -------------------------------------------------------------------------------------


def test_each_traced_node_records_agent_input_output_and_timestamp():
    received = []

    class Sink:
        def trace(self, entry):
            received.append(entry)

    def human_review(state):
        return {"decision": "approve"}

    node = tracing.traced("parte_3", "warehouse_human_review", "Ana Whitfield", human_review, input_keys=("round",))
    state = {"round": 1, "markdown": "x" * 1000, "department_id": "warehouse"}

    output = node(state, {"configurable": {"trace_sink": Sink()}})

    [entry] = output["trace"]
    assert output["decision"] == "approve" and received == [entry]
    assert entry["agent"] == "Ana Whitfield" and entry["department_id"] == "warehouse"
    assert entry["input"] == {"round": 1} and entry["output"] == {"decision": "approve"}
    assert datetime.fromisoformat(entry["timestamp"]).tzinfo is not None


def test_the_trace_keeps_long_values_short_and_skips_the_document():
    compacted = tracing.compact({"markdown": "documento", "draft": "a" * 500, "items": list(range(20))})

    assert "markdown" not in compacted
    assert compacted["draft"].endswith("(500 caracteres)") and len(compacted["items"]) == tracing.MAX_ITEMS + 1
