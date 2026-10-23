"""Grafo de la Parte 3: aprobación humana por departamento, arbitraje y cierre del documento.

    START → check_conflicts ─┬─ (trigger del BRIEFING §7) → arbitrate ─┐
                             └─ (sin conflictos) ───────────────────────┤
        ┌───────────────────────────────────────────────────────────────┘
        ├─ Send → warehouse_approval / lastmile_approval / reverse_approval
        │         (solo las no aprobadas, en paralelo) → check_conflicts
        ├─ (todas aprobadas) → finalize_document → END
        └─ (alguna rechazada) → close_without_document → END

Cada `<dept>_approval` ejecuta el subgrafo de su departamento:

    START → revise_section → request_review → human_review (interrupt) → record_decision ─┐
    ┌──────────────────────────────────────────────────────────────────────────────────────┘
    ├─ request_changes → revise_section
    └─ approve / reject → END

- **Interrupción acotada a su rama.** `human_review` llama a `interrupt` dentro del subgrafo del departamento. Con
  varios departamentos esperando, el checkpoint guarda una interrupción por rama; reanudar una (`Command(resume=
  {interrupt_id: decisión})`) hace avanzar solo esa rama —que puede aprobarse, o pedir cambios, regenerarse y volver a
  revisión— mientras las demás siguen esperando. `check_conflicts` y `finalize_document` corren cuando todas las
  ramas han terminado.
- **Reanudación, no reinicio.** El subgrafo hereda el checkpointer del grafo padre (hilo `rfp-{ticket_id}`, un
  namespace de checkpoint por rama): al reanudar, cada rama continúa desde su último nodo terminado.
- **Revisión.** `revise_section` reutiliza el ciclo generador-evaluador de la Parte 2 (`response_graph.
  revision_graphs`) con el comentario del responsable o la instrucción del árbitro como feedback.
- **Límites.** Una sección admite como mucho `max_rounds` revisiones (pedidas por su responsable o por el árbitro);
  después solo se puede aprobar o rechazar. `arbitrate` corre como mucho `max_rounds` rondas: al agotarlas, la regla
  del BRIEFING rechaza la sección ofensora y no hay documento final.
- **Árbitro fijo.** `arbitrate` aplica las reglas de `conflicts.py` sobre hechos extraídos en código; ningún modelo
  decide un desacuerdo.
- **Persistencia y traza.** El grafo informa a la base de datos por el `ApprovalSink` de `config["configurable"]`
  (estado de sección y ticket, arbitrajes, documento final) y cada nodo deja su entrada en `trace`.
"""

from __future__ import annotations

import logging
import os
import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from data.pipelines.rfp_intake import approval, conflicts, final_document, response_graph
from data.pipelines.rfp_intake.departments import DEPARTMENTS, ApprovalStatus, TicketStatus
from data.pipelines.rfp_intake.tracing import traced


logger = logging.getLogger("trackflow.rfp_intake")

PART = "parte_3"
DEFAULT_MAX_ROUNDS = 3
CHECK_CONFLICTS = "check_conflicts"
ARBITRATE = "arbitrate"
FINALIZE_DOCUMENT = "finalize_document"
CLOSE_WITHOUT_DOCUMENT = "close_without_document"
REVISE_SECTION = "revise_section"
REQUEST_REVIEW = "request_review"
HUMAN_REVIEW = "human_review"
RECORD_DECISION = "record_decision"


def approval_node_name(department_id: str) -> str:
    return f"{department_id}_approval"


class ApprovalSink(Protocol):
    """Lo que el grafo necesita de la base de datos (el runner lo implementa sobre PostgreSQL)."""

    def section_update(self, department_id: str, **fields: Any) -> None: ...
    def ticket_status(self, status: str) -> None: ...
    def arbitration(self, record: dict[str, Any]) -> None: ...
    def final_document(self, document: dict[str, Any]) -> None: ...
    def trace(self, entry: dict[str, Any]) -> None: ...


def merge_sections(left: dict[str, dict], right: dict[str, dict]) -> dict[str, dict]:
    """Cada rama devuelve solo su sección: las ramas paralelas no se pisan."""
    return {**(left or {}), **(right or {})}


class ApprovalState(TypedDict, total=False):
    ticket_id: str
    rfp_id: str | None
    shared: dict[str, Any]
    workstreams: dict[str, dict[str, Any]]
    max_rounds: int
    max_iterations: int
    sections: Annotated[dict[str, dict[str, Any]], merge_sections]
    # Hechos estructurados por sección (`conflicts.SectionFacts`) y triggers detectados sobre ellos.
    facts: dict[str, dict[str, Any]]
    conflicts: list[dict[str, Any]]
    arbitration_round: int
    arbitrations: Annotated[list[dict[str, Any]], operator.add]
    final_document: dict[str, Any] | None
    outcome: str
    trace: Annotated[list[dict[str, Any]], operator.add]


class ReviewState(TypedDict, total=False):
    ticket_id: str
    department_id: str
    brief: dict[str, Any]
    max_rounds: int
    max_iterations: int
    section: dict[str, Any]
    decision: dict[str, Any]
    trace: Annotated[list[dict[str, Any]], operator.add]


def _sink(config: RunnableConfig) -> ApprovalSink | None:
    return (config.get("configurable") or {}).get("approval_sink")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Subgrafo por departamento -----------------------------------------------------------------


def revise_section(state: ReviewState, config: RunnableConfig) -> dict[str, Any]:
    """Si hay una petición de cambios (del responsable o del árbitro), pasa otra vez por el ciclo de la Parte 2."""
    section = state["section"]
    instruction = section.get("instruction")
    if not instruction:
        return {}
    department_id = state["department_id"]
    result = response_graph.revision_graphs[department_id].invoke(
        {
            "ticket_id": state["ticket_id"],
            "department_id": department_id,
            # La instrucción va también en el brief: el feedback del juez sustituye al de la primera iteración, y sin
            # ella el generador podría deshacer el cambio pedido para responder a la evaluación.
            "brief": {**state["brief"], "revision_instructions": instruction.splitlines()},
            "max_iterations": state["max_iterations"],
            "draft": section["draft_content"],
            "feedback": instruction,
            "iteration": 0,
            "history": section.get("evaluation_history", []),
            "trace": [],
        },
        {**config, "recursion_limit": 3 * state["max_iterations"] + 10},
    )
    revised = {
        **section,
        "draft_content": result["draft"],
        "draft_status": result["status"],
        "iterations": result["iteration"],
        "evaluation_result": result["evaluation"],
        "evaluation_history": result["history"],
        "revisions": section["revisions"] + 1,
        "instruction": None,
    }
    logger.info(
        "ticket=%s node=%s_revise_section revisions=%s status=%s",
        state["ticket_id"],
        department_id,
        revised["revisions"],
        revised["draft_status"],
    )
    sink = _sink(config)
    if sink is not None:
        sink.section_update(department_id, revisions=revised["revisions"])
    return {"section": revised, "trace": result.get("trace", [])}


def request_review(state: ReviewState, config: RunnableConfig) -> dict[str, Any]:
    """Abre una nueva ronda de revisión humana y deja el ticket en `esperando_aprobación`."""
    section = {**state["section"], "approval_status": ApprovalStatus.PENDIENTE.value}
    section["review_round"] = section["review_round"] + 1
    sink = _sink(config)
    if sink is not None:
        sink.section_update(
            state["department_id"],
            approval_status=section["approval_status"],
            review_round=section["review_round"],
            approver=None,
            approved_at=None,
        )
        sink.ticket_status(TicketStatus.ESPERANDO_APROBACION.value)
    logger.info(
        "ticket=%s node=%s_request_review review_round=%s",
        state["ticket_id"],
        state["department_id"],
        section["review_round"],
    )
    return {"section": section}


def review_request(state: ReviewState) -> approval.ReviewRequest:
    section, department_id = state["section"], state["department_id"]
    evaluation = section.get("evaluation_result") or {}
    return approval.ReviewRequest(
        ticket_id=state["ticket_id"],
        department_id=department_id,
        approver=DEPARTMENTS[department_id].responsible,
        review_round=section["review_round"],
        revisions=section["revisions"],
        max_rounds=state["max_rounds"],
        draft_status=section.get("draft_status"),
        evaluation_pass=evaluation.get("overall_pass"),
        failed_rules=(evaluation.get("compliance") or {}).get("rule_ids", []),
        arbitration_notes=section.get("arbitration_notes", []),
        allowed_decisions=approval.allowed_decisions(section["revisions"], state["max_rounds"]),
    )


def human_review(state: ReviewState) -> dict[str, Any]:
    """Pausa solo esta rama hasta que el responsable decida. La decisión ya llega validada por el runner."""
    request = review_request(state)
    raw = interrupt(request.model_dump())
    decision = approval.ApprovalDecision.model_validate(raw)
    approval.check_against(decision, request.model_dump())
    return {"decision": decision.model_dump()}


def record_decision(state: ReviewState, config: RunnableConfig) -> dict[str, Any]:
    decision, section, department_id = state["decision"], dict(state["section"]), state["department_id"]
    responsible = DEPARTMENTS[department_id].responsible
    decided_at = _now()
    history_entry = {**decision, "approver": responsible, "decided_at": decided_at}
    section["decisions"] = [*section.get("decisions", []), history_entry]
    fields: dict[str, Any] = {}
    if decision["decision"] == "approve":
        section.update(approval_status=ApprovalStatus.APROBADA.value, approver=responsible, approved_at=decided_at)
        fields = {"approver": responsible, "approved_at": datetime.fromisoformat(decided_at)}
        capacity = decision.get("committed_monthly_capacity")
        if capacity:
            # La capacidad que firma Ana Whitfield queda también en el texto aprobado de su sección.
            section["committed_monthly_capacity"] = capacity
            section["draft_content"] = conflicts.with_committed_capacity(section["draft_content"], capacity)
            fields["draft_content"] = section["draft_content"]
    elif decision["decision"] == "request_changes":
        section.update(
            approval_status=ApprovalStatus.CAMBIOS_SOLICITADOS.value,
            instruction=f"Petición de cambios de {responsible} (responsable de la sección): {decision['comment']}",
        )
    else:
        section.update(approval_status=ApprovalStatus.RECHAZADA.value)
    sink = _sink(config)
    if sink is not None:
        sink.section_update(
            department_id,
            approval_status=section["approval_status"],
            approval_history=section["decisions"],
            **fields,
        )
    logger.info(
        "ticket=%s node=%s_record_decision decision=%s review_round=%s decided_by=%s",
        state["ticket_id"],
        department_id,
        decision["decision"],
        decision["review_round"],
        decision["decided_by"],
    )
    return {"section": section}


def route_after_decision(state: ReviewState) -> str:
    return REVISE_SECTION if state["decision"]["decision"] == "request_changes" else END


def define_review_graph(department_id: str) -> StateGraph:
    responsible = DEPARTMENTS[department_id].responsible
    builder = StateGraph(ReviewState)
    nodes = {
        REVISE_SECTION: (f"{department_id}_generator", revise_section),
        REQUEST_REVIEW: ("approval_coordinator", request_review),
        HUMAN_REVIEW: (responsible, human_review),
        RECORD_DECISION: ("approval_registry", record_decision),
    }
    for name, (agent, function) in nodes.items():
        builder.add_node(
            name,
            traced(PART, f"{department_id}_{name}", agent, function, department_id=department_id, input_keys=()),
        )
    builder.add_edge(START, REVISE_SECTION)
    builder.add_edge(REVISE_SECTION, REQUEST_REVIEW)
    builder.add_edge(REQUEST_REVIEW, HUMAN_REVIEW)
    builder.add_edge(HUMAN_REVIEW, RECORD_DECISION)
    builder.add_conditional_edges(RECORD_DECISION, route_after_decision, [REVISE_SECTION, END])
    return builder


# Sin checkpointer propio: hereda el del grafo padre y guarda su progreso en el namespace de su rama.
review_graphs = {department_id: define_review_graph(department_id).compile() for department_id in DEPARTMENTS}


def make_approval(department_id: str):
    def department_approval(payload: ReviewState, config: RunnableConfig) -> dict[str, Any]:
        result = review_graphs[department_id].invoke(payload, config)
        return {"sections": {department_id: result["section"]}, "trace": result.get("trace", [])}

    department_approval.__name__ = approval_node_name(department_id)
    return department_approval


# --- Grafo principal ---------------------------------------------------------------------------



def check_conflicts(state: ApprovalState) -> dict[str, Any]:
    """Extrae los hechos estructurados de cada sección y busca los triggers del BRIEFING §7."""
    facts = {
        department_id: conflicts.extract_facts(
            department_id, section["draft_content"] or "", section.get("committed_monthly_capacity")
        )
        for department_id, section in state["sections"].items()
        if section["approval_status"] != ApprovalStatus.RECHAZADA.value
    }
    found = [conflict.as_dict() for conflict in conflicts.detect(facts, state["shared"].get("currency"))]
    logger.info(
        "ticket=%s node=check_conflicts triggers=%s",
        state["ticket_id"],
        [conflict["trigger_id"] for conflict in found],
    )
    return {"conflicts": found, "facts": {d: f.as_dict() for d, f in facts.items()}}


def arbitrate(state: ApprovalState, config: RunnableConfig) -> dict[str, Any]:
    """Resuelve cada conflicto con la regla y el árbitro fijos del BRIEFING; nunca con un modelo."""
    round_number = state.get("arbitration_round", 0) + 1
    exhausted = round_number > state["max_rounds"]
    sections = {department_id: dict(section) for department_id, section in state["sections"].items()}
    records = []
    for conflict in state["conflicts"]:
        for department_id, instruction in conflict["instructions"].items():
            section = sections[department_id]
            note = f"[{conflict['trigger_id']}] {conflict['arbiter']}: {conflict['rule']}"
            section["arbitration_notes"] = [*section.get("arbitration_notes", []), note]
            if exhausted or section["revisions"] >= state["max_rounds"]:
                section["approval_status"] = ApprovalStatus.RECHAZADA.value
                action = "reject"
            else:
                section["approval_status"] = ApprovalStatus.CAMBIOS_SOLICITADOS.value
                # Si dos triggers tocan la misma sección, el generador recibe las dos instrucciones.
                previous = section.get("instruction")
                section["instruction"] = f"{previous}\n{instruction}" if previous else instruction
                action = "request_changes"
            records.append(
                {
                    "round": round_number,
                    "trigger_id": conflict["trigger_id"],
                    "arbiter": conflict["arbiter"],
                    "rule": conflict["rule"],
                    "department_id": department_id,
                    "action": action,
                    "instruction": instruction if action == "request_changes" else None,
                    "evidence": conflict["evidence"],
                    "decided_at": _now(),
                }
            )
    sink = _sink(config)
    for record in records:
        logger.warning(
            "ticket=%s node=arbitrate round=%s/%s trigger=%s arbiter=%s department=%s action=%s",
            state["ticket_id"],
            round_number,
            state["max_rounds"],
            record["trigger_id"],
            record["arbiter"],
            record["department_id"],
            record["action"],
        )
        if sink is not None:
            department_id = record["department_id"]
            sink.arbitration(record)
            sink.section_update(department_id, approval_status=sections[department_id]["approval_status"])
    return {"sections": sections, "arbitration_round": round_number, "arbitrations": records, "conflicts": []}


def route_after_check(state: ApprovalState) -> list[Send] | str:
    if state.get("conflicts"):
        return ARBITRATE
    return route_sections(state)


def route_sections(state: ApprovalState) -> list[Send] | str:
    sections = state["sections"]
    if any(section["approval_status"] == ApprovalStatus.RECHAZADA.value for section in sections.values()):
        return CLOSE_WITHOUT_DOCUMENT
    pending = [d for d, section in sections.items() if section["approval_status"] != ApprovalStatus.APROBADA.value]
    if not pending:
        return FINALIZE_DOCUMENT
    return [
        Send(
            approval_node_name(department_id),
            ReviewState(
                ticket_id=state["ticket_id"],
                department_id=department_id,
                brief={**state["shared"], "department": state["workstreams"][department_id]},
                max_rounds=state["max_rounds"],
                max_iterations=state["max_iterations"],
                section=sections[department_id],
                trace=[],
            ),
        )
        for department_id in pending
    ]


def finalize_document(state: ApprovalState, config: RunnableConfig) -> dict[str, Any]:
    document = final_document.build(
        state["ticket_id"],
        state.get("rfp_id"),
        state["shared"],
        list(state["sections"].values()),
        datetime.now(timezone.utc),
    )
    sink = _sink(config)
    if sink is not None:
        sink.final_document(document)
    logger.info(
        "ticket=%s node=finalize_document sections=%s currency=%s",
        state["ticket_id"],
        [section["department_id"] for section in document["sections"]],
        document["currency"],
    )
    return {"final_document": document, "outcome": TicketStatus.TERMINADO.value}


def close_without_document(state: ApprovalState) -> dict[str, Any]:
    rejected = [
        department_id
        for department_id, section in state["sections"].items()
        if section["approval_status"] == ApprovalStatus.RECHAZADA.value
    ]
    logger.warning(
        "ticket=%s node=close_without_document rejected=%s: no se genera documento final.", state["ticket_id"], rejected
    )
    return {"outcome": "sin_documento", "final_document": None}


def define_graph() -> StateGraph:
    builder = StateGraph(ApprovalState)
    approval_names = [approval_node_name(department_id) for department_id in DEPARTMENTS]
    builder.add_node(
        CHECK_CONFLICTS,
        traced(PART, CHECK_CONFLICTS, "conflict_detector", check_conflicts, input_keys=("arbitration_round",)),
    )
    builder.add_node(
        ARBITRATE,
        traced(PART, ARBITRATE, "árbitro (BRIEFING §7)", arbitrate, input_keys=("conflicts", "arbitration_round")),
    )
    for department_id in DEPARTMENTS:
        name = approval_node_name(department_id)
        branch = make_approval(department_id)
        builder.add_node(
            name, traced(PART, name, "approval_branch", branch, department_id=department_id, input_keys=())
        )
    builder.add_node(
        FINALIZE_DOCUMENT, traced(PART, FINALIZE_DOCUMENT, "document_synthesizer", finalize_document, input_keys=())
    )
    builder.add_node(
        CLOSE_WITHOUT_DOCUMENT,
        traced(PART, CLOSE_WITHOUT_DOCUMENT, "approval_coordinator", close_without_document, input_keys=()),
    )

    targets = [*approval_names, FINALIZE_DOCUMENT, CLOSE_WITHOUT_DOCUMENT]
    builder.add_edge(START, CHECK_CONFLICTS)
    builder.add_conditional_edges(CHECK_CONFLICTS, route_after_check, [ARBITRATE, *targets])
    builder.add_conditional_edges(ARBITRATE, route_sections, targets)
    for name in approval_names:
        builder.add_edge(name, CHECK_CONFLICTS)
    builder.add_edge(FINALIZE_DOCUMENT, END)
    builder.add_edge(CLOSE_WITHOUT_DOCUMENT, END)
    return builder


def max_rounds_from_env() -> int:
    """`RFP_MAX_APPROVAL_ROUNDS` (por defecto 3): revisiones por sección y rondas de arbitraje."""
    value = int(os.getenv("RFP_MAX_APPROVAL_ROUNDS", str(DEFAULT_MAX_ROUNDS)))
    if value < 1:
        raise ValueError("RFP_MAX_APPROVAL_ROUNDS tiene que ser al menos 1.")
    return value
