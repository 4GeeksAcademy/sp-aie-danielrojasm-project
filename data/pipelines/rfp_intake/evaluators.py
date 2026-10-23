"""Agentes evaluadores de la Parte 2 y el `EvaluationResult` que persiste cada sección.

Los tres corren en paralelo sobre cada borrador (`response_graph.py`) y cada uno recibe solo lo que necesita:

- `evaluate_readability`: solo el borrador. `py-readability-metrics` sobre la prosa (sin tablas ni marcas de
  Markdown). Pasa con 100-600 palabras y Flesch-Kincaid ≤ 14: la fórmula está calibrada para inglés y puntúa más
  alto el español; un texto comercial claro en español da ~11-12.
- `evaluate_relevance`: el borrador y los `key_aspects` de su departamento (handoff de la Parte 1), nunca el
  documento entero. El modelo solo señala qué aspectos (por número) no responde; la lista sale del handoff, así que
  no puede inventar aspectos.
- `evaluate_compliance`: el borrador y la moneda. Las reglas del BRIEFING §5 (`compliance.py`) se comprueban en
  código; el revisor con modelo solo añade violaciones de `LLM_REVIEWED_RULES` con una cita literal del borrador.

`judge` junta los tres resultados y, si algo falla, redacta `feedback_for_generator` a partir de los fallos
concretos (aspecto que falta, regla, cita y cómo corregirlo), no un "mejóralo" genérico.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from readability import Readability
from readability.exceptions import ReadabilityException

from data.pipelines.rfp_intake import compliance, llm
from data.pipelines.rfp_intake.departments import DEPARTMENTS
from data.pipelines.rfp_intake.document import ensure_sentence_tokenizer


logger = logging.getLogger("trackflow.rfp_intake")

MIN_WORDS = 100
MAX_WORDS = 600
MAX_GRADE = 14.0

MARKDOWN_MARKS = re.compile(r"^\s{0,3}(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s+)|\*\*|__|`")


# --- EvaluationResult ---------------------------------------------------------------------------


class _Result(BaseModel):
    # `pass` es palabra reservada en Python: el atributo es `passed` y el JSON usa `pass`.
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    passed: bool = Field(alias="pass")


class ReadabilityResult(_Result):
    score: float | None = Field(description="Flesch-Kincaid grade de la prosa; `None` si no se pudo medir.")
    details: str
    metrics: dict[str, float | int | None] = Field(default_factory=dict)


class RelevanceResult(_Result):
    missing_aspects: list[str] = Field(default_factory=list)
    checked_aspects: int = 0


class ComplianceViolation(BaseModel):
    rule_id: str
    detail: str
    evidence: str = ""
    source: str = "regla"


class ComplianceResult(_Result):
    rule_ids: list[str] = Field(default_factory=list, description="Reglas incumplidas (vacía si pasa).")
    violations: list[ComplianceViolation] = Field(default_factory=list)
    checked_rule_ids: list[str] = Field(default_factory=lambda: list(compliance.RULES))


class EvaluationResult(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    section_id: str
    department_id: str
    iteration: int
    readability: ReadabilityResult
    relevance: RelevanceResult
    compliance: ComplianceResult
    overall_pass: bool
    feedback_for_generator: str


# --- Legibilidad -------------------------------------------------------------------------------


def prose_of(draft: str) -> str:
    """El texto que se lee como prosa: sin tablas y sin marcas de Markdown."""
    lines = []
    for line in draft.splitlines():
        if line.strip().startswith("|"):
            continue
        cleaned = MARKDOWN_MARKS.sub("", line).strip()
        if cleaned:
            # Un título o una viñeta sin punto final se cuenta como frase propia.
            lines.append(cleaned if cleaned[-1] in ".:;!?" else f"{cleaned}.")
    return "\n".join(lines)


def evaluate_readability(draft: str) -> ReadabilityResult:
    prose = prose_of(draft)
    words = len(prose.split())
    metrics: dict[str, float | int | None] = {
        "word_count": words,
        "flesch_kincaid_grade": None,
        "flesch_reading_ease": None,
        "gunning_fog": None,
    }
    if words < MIN_WORDS:
        return ReadabilityResult(
            passed=False,
            score=None,
            details=f"La prosa tiene {words} palabras; el mínimo para una sección de propuesta es {MIN_WORDS}.",
            metrics=metrics,
        )
    try:
        ensure_sentence_tokenizer()
        scores = Readability(prose)
        grade = round(scores.flesch_kincaid().score, 2)
        metrics.update(
            flesch_kincaid_grade=grade,
            flesch_reading_ease=round(scores.flesch().score, 2),
            gunning_fog=round(scores.gunning_fog().score, 2),
        )
    except (ReadabilityException, LookupError) as error:
        # Sin métricas no se puede afirmar que sea legible: falla y lo dice, en vez de aprobar a ciegas.
        logger.warning("readability_evaluator sin métricas: %s", type(error).__name__)
        return ReadabilityResult(
            passed=False, score=None, details="No se pudo medir la legibilidad de la sección.", metrics=metrics
        )
    problems = []
    if words > MAX_WORDS:
        problems.append(f"la prosa tiene {words} palabras (máximo {MAX_WORDS}): resume")
    if grade > MAX_GRADE:
        problems.append(
            f"Flesch-Kincaid {grade} (máximo {MAX_GRADE}): usa frases más cortas, de una idea, y palabras más "
            "simples"
        )
    details = (
        f"Legible: {words} palabras, Flesch-Kincaid {grade}."
        if not problems
        else "Legibilidad insuficiente: " + "; ".join(problems) + "."
    )
    return ReadabilityResult(passed=not problems, score=grade, details=details, metrics=metrics)


# --- Pertinencia -------------------------------------------------------------------------------


RELEVANCE_PROMPT = """Eres el evaluador de pertinencia de las propuestas económicas de TrackFlow. Recibes la sección
de un departamento y la lista numerada de aspectos clave que la RFP del cliente pide a ese departamento (salen del
análisis de la RFP). Decide qué aspectos NO responde la sección. Un aspecto está respondido si la sección lo
aborda de forma explícita: con un precio, un plazo, una capacidad o una condición concreta; marcándolo como
pendiente ("a confirmar con …") si TrackFlow aún no puede comprometerlo; o con una pregunta al cliente si falta el
dato. Un aspecto que solo describe al cliente (tipo de marca, ubicación, situación actual) está respondido si el
alcance de la sección lo tiene en cuenta. Mencionarlo de pasada sin ninguna respuesta no cuenta.

No evalúes estilo, cifras ni lineamientos: solo si responde a lo que pide la RFP.
Responde solo con JSON: {"missing_aspect_ids": [números de los aspectos no respondidos], "notes": "..."}"""


class RelevanceOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    missing_aspect_ids: list[int] = Field(default_factory=list)
    notes: str = ""


def evaluate_relevance(department_id: str, draft: str, key_aspects: list[str]) -> RelevanceResult:
    if not key_aspects:
        return RelevanceResult(passed=True, checked_aspects=0)
    aspects = "\n".join(f"{index}. {aspect}" for index, aspect in enumerate(key_aspects, start=1))
    prompt = (
        f"DEPARTAMENTO: {DEPARTMENTS[department_id].name}\n\nASPECTOS CLAVE DE LA RFP:\n"
        f"{llm.as_document(aspects)}\n\nSECCIÓN A EVALUAR:\n<seccion>\n{draft}\n</seccion>"
    )
    output = llm.ask_json(f"{department_id}_relevance_evaluator", RELEVANCE_PROMPT, prompt, RelevanceOutput)
    # Solo números de la lista: el modelo no puede añadir aspectos que la RFP no pide.
    ids = [index for index in dict.fromkeys(output.missing_aspect_ids) if 1 <= index <= len(key_aspects)]
    missing = [key_aspects[index - 1] for index in ids]
    return RelevanceResult(passed=not missing, missing_aspects=missing, checked_aspects=len(key_aspects))


# --- Cumplimiento ------------------------------------------------------------------------------


COMPLIANCE_PROMPT = """Eres el revisor de cumplimiento de las propuestas económicas de TrackFlow. Revisa la sección
SOLO contra estas reglas de empresa:
{rules}

Señala una violación solo si la sección la contiene de verdad, citando en "evidence" el fragmento literal (copiado
tal cual) donde ocurre. No opines sobre estilo ni sobre otras reglas. Si no hay violaciones, devuelve [].
Responde solo con JSON: {{"violations": [{{"rule_id": "...", "evidence": "...", "detail": "..."}}]}}"""


class ReviewerViolation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rule_id: str
    evidence: str = ""
    detail: str = ""


class ComplianceReviewOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    violations: list[ReviewerViolation] = Field(default_factory=list)


def evaluate_compliance(department_id: str, draft: str, currency: str | None) -> ComplianceResult:
    violations = compliance.check(draft, currency)
    violations.extend(_reviewer_violations(department_id, draft, violations))
    return ComplianceResult(
        passed=not violations,
        rule_ids=sorted({violation.rule_id for violation in violations}),
        violations=[ComplianceViolation(**violation.as_dict()) for violation in violations],
    )


def _reviewer_violations(
    department_id: str, draft: str, found: list[compliance.Violation]
) -> list[compliance.Violation]:
    rules = "\n".join(
        f"- {rule_id}: {compliance.RULES[rule_id].guideline}" for rule_id in sorted(compliance.LLM_REVIEWED_RULES)
    )
    output = llm.ask_json(
        f"{department_id}_compliance_evaluator",
        COMPLIANCE_PROMPT.format(rules=rules),
        f"<seccion>\n{draft}\n</seccion>",
        ComplianceReviewOutput,
    )
    kept: list[compliance.Violation] = []
    for item in output.violations:
        if item.rule_id not in compliance.LLM_REVIEWED_RULES or not compliance.evidence_in(draft, item.evidence):
            # Sin regla del catálogo o sin cita literal no es una violación verificable, es una opinión.
            logger.info("%s_compliance_evaluator descarta una violación sin regla o sin cita literal.", department_id)
            continue
        evidence = item.evidence.strip()
        if any(v.rule_id == item.rule_id and _overlaps(v.evidence, evidence) for v in [*found, *kept]):
            continue  # Las reglas en código ya la detectaron.
        detail = item.detail.strip() or compliance.RULES[item.rule_id].guideline
        kept.append(compliance.Violation(item.rule_id, detail, evidence, source="revisor"))
    return kept


def _overlaps(first: str, second: str) -> bool:
    return bool(first and second) and (compliance.evidence_in(first, second) or compliance.evidence_in(second, first))


# --- Veredicto y feedback ----------------------------------------------------------------------


def judge(
    ticket_id: str,
    department_id: str,
    iteration: int,
    readability: ReadabilityResult,
    relevance: RelevanceResult,
    compliance_result: ComplianceResult,
) -> EvaluationResult:
    overall = readability.passed and relevance.passed and compliance_result.passed
    return EvaluationResult(
        section_id=f"{ticket_id}:{department_id}",
        department_id=department_id,
        iteration=iteration,
        readability=readability,
        relevance=relevance,
        compliance=compliance_result,
        overall_pass=overall,
        feedback_for_generator="" if overall else feedback(readability, relevance, compliance_result),
    )


def feedback(readability: ReadabilityResult, relevance: RelevanceResult, compliance_result: ComplianceResult) -> str:
    items: list[str] = []
    if not readability.passed:
        items.append(f"Legibilidad: {readability.details}")
    if not relevance.passed:
        missing = "; ".join(f'"{aspect}"' for aspect in relevance.missing_aspects)
        items.append(
            f"Pertinencia: la sección no responde a estos aspectos de la RFP: {missing}. Añade para cada uno una "
            "frase explícita: un precio, plazo, capacidad o condición concreta; 'a confirmar con' el responsable si "
            "TrackFlow aún no puede comprometerlo; o una pregunta al cliente si falta el dato."
        )
    for violation in compliance_result.violations:
        quote = f' Texto: "{violation.evidence}".' if violation.evidence else ""
        items.append(
            f"Cumplimiento [{violation.rule_id}]: {violation.detail}{quote} Cómo corregirlo: "
            f"{compliance.RULES[violation.rule_id].fix}"
        )
    return "\n".join(f"- {item}" for item in items)


def as_json(result: BaseModel) -> dict[str, Any]:
    return json.loads(result.model_dump_json(by_alias=True))
