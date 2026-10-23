"""Agentes de la Parte 2: generadores por departamento y evaluadores de legibilidad, pertinencia y cumplimiento.

Sin gateway LLM: `llm.ask_json` devuelve la salida que daría el modelo y los tests comprueban lo que decide el
código encima (las reglas del BRIEFING §5, el veredicto y el feedback para el generador).
"""

import pytest

from data.pipelines.rfp_intake import compliance, evaluators, generators, llm
from data.process.rag import RagServiceError


RETURNS_ASPECTS = [
    "Gestión de devoluciones: inspección, reacondicionamiento y restock",
    "Centro cercano a Zaragoza",
]


def reverse_draft(processing: str = "a partir de 48 horas", sla: str = "un SLA del 90 % de entregas a tiempo") -> str:
    """Sección de Reverse Logistics para ModaViva (España → EUR) que cumple los lineamientos con los valores por defecto."""
    return f"""## Reverse Logistics — Propuesta económica
**Responsable:** Sofía Ramos · **Moneda:** EUR

### Alcance
TrackFlow gestiona las devoluciones de ModaViva en su centro de Zaragoza. El servicio incluye la recepción, la
inspección y la clasificación de cada producto. Cada artículo se clasifica como apto para reventa, apto para
reacondicionar o no apto. Después vuelve al stock según las reglas que defina ModaViva.

### Tarifas
| Concepto | Precio (EUR) | Unidad |
|---|---|---|
| Recepción e inspección | a confirmar con Sofía Ramos | por devolución |
| Reacondicionamiento y restock | a confirmar con Sofía Ramos | por unidad |

El procesamiento de cada devolución se completa {processing} desde su llegada al almacén. La ventana de devolución
estándar es de 30 días desde la entrega. El envío de vuelta lo paga la marca, salvo error de TrackFlow.

### Descuentos por volumen
| Devoluciones al mes | Descuento |
|---|---|
| Hasta 1.000 | 0 % |
| Más de 1.000 | 5 % |

Los descuentos están sujetos a la aprobación de Miguel Torres, Commercial Director.

### SLA de entrega a tiempo
TrackFlow se compromete a {sla} por mes, medido por país.

### Supuestos y datos pendientes
- El volumen mensual de devoluciones previsto está pendiente de confirmar por ModaViva.
"""


def fake_model(monkeypatch, responses: dict[str, dict], calls: list | None = None):
    """`responses` por sufijo del agente (`generator`, `relevance_evaluator`, `compliance_evaluator`)."""

    def ask_json(agent, system_prompt, user_prompt, schema):
        if calls is not None:
            calls.append({"agent": agent, "system": system_prompt, "user": user_prompt})
        suffix = next(key for key in responses if agent.endswith(key))
        return schema.model_validate(responses[suffix])

    monkeypatch.setattr(llm, "ask_json", ask_json)


# --- Generadores -------------------------------------------------------------------------------


BRIEF = {
    "client_name": "ModaViva, S.L.",
    "client_country": "ES",
    "currency": "EUR",
    "services_requested": ["warehousing", "reverse_logistics"],
    "monthly_volume": None,
    "deadline": "2026-08-28",
    "budget_range": None,
    "summary": "ModaViva (España, EUR) pide almacenamiento y devoluciones.",
    "conflicts": [],
    "department": {
        "department_id": "reverse",
        "department_name": "Reverse Logistics",
        "responsible": "Sofía Ramos",
        "key_aspects": RETURNS_ASPECTS,
        "requested_inputs": ["Costo por devolución procesada"],
        "open_questions": ["Volumen mensual de devoluciones"],
    },
}


def test_each_department_has_its_own_generator_with_its_own_scope():
    assert set(generators.GENERATORS) == {"warehouse", "lastmile", "reverse"}
    contents = {spec.content for spec in generators.GENERATORS.values()}
    assert len(contents) == 3


def test_generator_drafts_from_the_part_1_handoff_with_currency_rules_and_knowledge(monkeypatch):
    calls: list = []
    fake_model(monkeypatch, {"generator": {"content": reverse_draft()}}, calls)

    draft = generators.generate("reverse", BRIEF, ["[trackflow-returns-policy.es.md] Ventana de 30 días."])

    assert draft.startswith("## Reverse Logistics")
    call = calls[0]
    assert call["agent"] == "reverse_generator"
    assert "Sofía Ramos" in call["system"] and "Moneda:** EUR" in call["system"]
    for rule_id in compliance.RULES:
        assert rule_id in call["system"]
    assert RETURNS_ASPECTS[0] in call["user"] and "Ventana de 30 días" in call["user"]
    assert "BORRADOR ANTERIOR" not in call["user"]


def test_generator_receives_its_previous_draft_and_the_feedback_on_a_retry(monkeypatch):
    calls: list = []
    fake_model(monkeypatch, {"generator": {"content": reverse_draft()}}, calls)
    feedback = "- Cumplimiento [returns-min-48h]: Promete un plazo de devoluciones inferior a 48 horas (24 horas)."

    generators.generate("reverse", BRIEF, [], previous_draft=reverse_draft("en 24 horas"), feedback=feedback)

    user = calls[0]["user"]
    assert "en 24 horas" in user and feedback in user
    assert "la base de conocimiento no respondió" in user


def test_generator_without_a_valid_output_raises_instead_of_inventing_a_section(monkeypatch):
    fake_model(monkeypatch, {"generator": {"content": ""}})

    with pytest.raises(Exception):
        generators.generate("reverse", BRIEF, [])


def test_knowledge_is_deduplicated_and_optional(monkeypatch):
    chunk = {"source_document": "trackflow-sla-delivery.es.md", "chunk_index": 0, "text": "SLA del 90% mensual."}
    monkeypatch.setattr(generators.rag, "retrieve", lambda query, k: [chunk])
    assert generators.retrieve_knowledge("warehouse") == ["[trackflow-sla-delivery.es.md] SLA del 90% mensual."]

    def qdrant_down(query, k):
        raise RagServiceError("Qdrant no respondió a la búsqueda.")

    monkeypatch.setattr(generators.rag, "retrieve", qdrant_down)
    assert generators.retrieve_knowledge("warehouse") == []


# --- Legibilidad -------------------------------------------------------------------------------


def test_readability_passes_a_clear_section_and_ignores_tables():
    result = evaluators.evaluate_readability(reverse_draft())

    assert result.passed is True, result.details
    assert result.score is not None and result.score <= evaluators.MAX_GRADE
    assert result.metrics["word_count"] >= evaluators.MIN_WORDS
    assert "|" not in evaluators.prose_of(reverse_draft())


def test_readability_fails_a_section_that_is_too_short():
    result = evaluators.evaluate_readability("## Reverse Logistics\nPrecio a confirmar.")

    assert result.passed is False
    assert "mínimo" in result.details


def test_readability_fails_convoluted_prose():
    sentence = (
        "La implementación de la infraestructura organizacional correspondiente a la administración "
        "multidimensional de procedimientos operativos interdepartamentales, considerando consideraciones "
        "contractuales extraordinariamente particularizadas y responsabilidades institucionales, "
    )
    result = evaluators.evaluate_readability((sentence * 6) + "permanece pendiente.")

    assert result.passed is False
    assert "Flesch-Kincaid" in result.details


# --- Pertinencia -------------------------------------------------------------------------------


def test_relevance_reports_only_aspects_from_the_handoff(monkeypatch):
    calls: list = []
    fake_model(monkeypatch, {"relevance_evaluator": {"missing_aspect_ids": [2, 2, 7], "notes": "No habla del centro."}}, calls)

    result = evaluators.evaluate_relevance("reverse", reverse_draft(), RETURNS_ASPECTS)

    assert result.passed is False
    assert result.missing_aspects == ["Centro cercano a Zaragoza"]
    # El evaluador recibe solo la sección y los aspectos de su departamento.
    assert calls[0]["agent"] == "reverse_relevance_evaluator"
    assert RETURNS_ASPECTS[0] in calls[0]["user"] and "ModaViva (España" not in calls[0]["user"]


# --- Cumplimiento ------------------------------------------------------------------------------


NO_REVIEWER_FINDINGS = {"compliance_evaluator": {"violations": []}}


def test_compliance_passes_a_section_that_follows_the_briefing(monkeypatch):
    fake_model(monkeypatch, NO_REVIEWER_FINDINGS)

    result = evaluators.evaluate_compliance("reverse", reverse_draft(), "EUR")

    assert result.passed is True, result.violations
    assert result.rule_ids == []
    assert result.checked_rule_ids == list(compliance.RULES)


def test_compliance_fails_a_returns_promise_under_48_hours(monkeypatch):
    """BRIEFING §5: ninguna propuesta puede prometer procesamiento de devoluciones en menos de 48 horas."""
    fake_model(monkeypatch, NO_REVIEWER_FINDINGS)

    result = evaluators.evaluate_compliance("reverse", reverse_draft(processing="en 24 horas"), "EUR")

    assert result.passed is False
    assert result.rule_ids == ["returns-min-48h"]
    assert "24 horas" in result.violations[0].evidence


@pytest.mark.parametrize(
    ("draft", "currency", "rule_id"),
    [
        (reverse_draft(), "USD", "currency-by-country"),
        (reverse_draft().replace("EUR", "EUR · 12 USD"), "EUR", "currency-by-country"),
        (reverse_draft(sla="cumplir los plazos acordados"), "EUR", "on-time-sla"),
        (reverse_draft().replace("| Hasta 1.000 | 0 % |\n| Más de 1.000 | 5 % |\n", ""), "EUR", "volume-discount-table"),
        (reverse_draft() + "\nLa tarifa negociada con SEUR es de 3,10 EUR por envío.\n", "EUR", "no-carrier-rates"),
        (reverse_draft(processing="el mismo día"), "EUR", "returns-min-48h"),
        (reverse_draft(processing="en menos de 48 horas"), "EUR", "returns-min-48h"),
    ],
)
def test_each_briefing_rule_has_a_deterministic_check(monkeypatch, draft, currency, rule_id):
    fake_model(monkeypatch, NO_REVIEWER_FINDINGS)

    result = evaluators.evaluate_compliance("reverse", draft, currency)

    assert result.passed is False
    assert rule_id in result.rule_ids


def test_a_negated_returns_statement_is_not_a_promise():
    draft = reverse_draft(processing="a partir de 48 horas (TrackFlow no procesa devoluciones en menos de 48 horas)")

    assert compliance.check_returns_turnaround(draft) == []


def test_the_reviewer_can_only_add_violations_of_its_rules_with_a_literal_quote(monkeypatch):
    draft = reverse_draft() + "\nNuestro socio de transporte nos cobra muy poco y te trasladamos ese precio.\n"
    fake_model(
        monkeypatch,
        {
            "compliance_evaluator": {
                "violations": [
                    {"rule_id": "no-carrier-rates", "evidence": "Nuestro socio de transporte nos cobra muy poco"},
                    {"rule_id": "no-carrier-rates", "evidence": "una frase que no está en el borrador"},
                    {"rule_id": "tono", "evidence": "TrackFlow gestiona las devoluciones"},
                ]
            }
        },
    )

    result = evaluators.evaluate_compliance("reverse", draft, "EUR")

    assert result.rule_ids == ["no-carrier-rates"]
    assert [(v.source, v.evidence) for v in result.violations] == [
        ("revisor", "Nuestro socio de transporte nos cobra muy poco")
    ]


# --- Veredicto ---------------------------------------------------------------------------------


def test_judge_builds_a_structured_result_with_actionable_feedback(monkeypatch):
    fake_model(monkeypatch, NO_REVIEWER_FINDINGS)
    readability = evaluators.evaluate_readability(reverse_draft(processing="en 24 horas"))
    relevance = evaluators.RelevanceResult(passed=False, missing_aspects=["Centro cercano a Zaragoza"], checked_aspects=2)
    compliance_result = evaluators.evaluate_compliance("reverse", reverse_draft(processing="en 24 horas"), "EUR")

    result = evaluators.judge("ticket-1", "reverse", 1, readability, relevance, compliance_result)
    payload = evaluators.as_json(result)

    assert payload["section_id"] == "ticket-1:reverse" and payload["overall_pass"] is False
    assert payload["readability"]["pass"] is True
    assert payload["relevance"] == {"pass": False, "missing_aspects": ["Centro cercano a Zaragoza"], "checked_aspects": 2}
    assert payload["compliance"]["pass"] is False and payload["compliance"]["rule_ids"] == ["returns-min-48h"]
    feedback = payload["feedback_for_generator"]
    assert '"Centro cercano a Zaragoza"' in feedback
    assert "[returns-min-48h]" in feedback and "en 24 horas" in feedback
    assert compliance.RULES["returns-min-48h"].fix in feedback


def test_judge_passes_without_feedback_when_all_evaluators_pass(monkeypatch):
    fake_model(monkeypatch, NO_REVIEWER_FINDINGS)

    result = evaluators.judge(
        "ticket-1",
        "reverse",
        1,
        evaluators.evaluate_readability(reverse_draft()),
        evaluators.RelevanceResult(passed=True, checked_aspects=2),
        evaluators.evaluate_compliance("reverse", reverse_draft(), "EUR"),
    )

    assert result.overall_pass is True
    assert result.feedback_for_generator == ""
