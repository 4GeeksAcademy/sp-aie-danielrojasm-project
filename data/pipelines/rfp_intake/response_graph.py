"""Grafo de la Parte 2: generación y evaluación de la propuesta económica por departamento.

    START ─ Send por workstream del handoff ─▶ warehouse_section / lastmile_section / reverse_section (en paralelo) → END

Cada `<dept>_section` ejecuta el subgrafo del ciclo generador-evaluador de su departamento:

    START → retrieve_knowledge → <dept>_generator ─┬─▶ readability_evaluator ─┐
                                                   ├─▶ relevance_evaluator  ──┼─▶ judge ─┬─ (pasa) → END
                                                   └─▶ compliance_evaluator ─┘           ├─ (falla, quedan iteraciones) → <dept>_generator
                                                                                         └─ (falla, límite agotado) → END (needs_human_review)

- Los departamentos son ramas independientes: uno que itera tres veces no retrasa la evaluación de otro.
- Los tres evaluadores corren en paralelo y cada uno escribe solo su clave del estado (`readability`, `relevance`,
  `compliance`), así que no se pisan; `judge` es el único que las lee y combina.
- Al agotar `max_iterations` sin pasar, la sección se conserva con su último borrador y su `EvaluationResult` y
  queda en `needs_human_review`; nunca se descarta.
- El grafo no conoce la base de datos: informa del progreso por el `ProgressSink` que recibe en
  `config["configurable"]["progress"]` (el runner lo usa para que el ticket refleje cada paso en PostgreSQL).
"""

from __future__ import annotations

import logging
import operator
import os
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from data.pipelines.rfp_intake import evaluators, generators
from data.pipelines.rfp_intake.departments import DEPARTMENTS, SectionStatus


logger = logging.getLogger("trackflow.rfp_intake")

DEFAULT_MAX_ITERATIONS = 3
RETRIEVE_KNOWLEDGE = "retrieve_knowledge"
READABILITY_EVALUATOR = "readability_evaluator"
RELEVANCE_EVALUATOR = "relevance_evaluator"
COMPLIANCE_EVALUATOR = "compliance_evaluator"
JUDGE = "judge"
EVALUATORS = (READABILITY_EVALUATOR, RELEVANCE_EVALUATOR, COMPLIANCE_EVALUATOR)


def max_iterations_from_env() -> int:
    """`RFP_MAX_GENERATION_ITERATIONS` (por defecto 3; la meta del BRIEFING §3 es menos de 2 de media)."""
    value = int(os.getenv("RFP_MAX_GENERATION_ITERATIONS", str(DEFAULT_MAX_ITERATIONS)))
    if value < 1:
        raise ValueError("RFP_MAX_GENERATION_ITERATIONS tiene que ser al menos 1.")
    return value


def generator_node_name(department_id: str) -> str:
    return f"{department_id}_generator"


def section_node_name(department_id: str) -> str:
    return f"{department_id}_section"


class ProgressSink(Protocol):
    def section_update(self, department_id: str, **fields: Any) -> None: ...


class SectionState(TypedDict, total=False):
    ticket_id: str
    department_id: str
    brief: dict[str, Any]
    max_iterations: int
    knowledge: list[str]
    iteration: int
    draft: str
    feedback: str
    # Una clave por evaluador: escriben en paralelo sin conflicto.
    readability: dict[str, Any]
    relevance: dict[str, Any]
    compliance: dict[str, Any]
    evaluation: dict[str, Any]
    history: Annotated[list[dict[str, Any]], operator.add]
    status: str


class ResponseState(TypedDict, total=False):
    ticket_id: str
    shared: dict[str, Any]
    workstreams: list[dict[str, Any]]
    max_iterations: int
    sections: Annotated[list[dict[str, Any]], operator.add]


def _report(config: RunnableConfig, department_id: str, **fields: Any) -> None:
    progress = (config.get("configurable") or {}).get("progress")
    if progress is not None:
        progress.section_update(department_id, **fields)


# --- Subgrafo por departamento -----------------------------------------------------------------


def retrieve_knowledge(state: SectionState) -> dict[str, Any]:
    return {"knowledge": generators.retrieve_knowledge(state["department_id"])}


def make_generator(department_id: str):
    def generator(state: SectionState, config: RunnableConfig) -> dict[str, Any]:
        iteration = state.get("iteration", 0) + 1
        _report(config, department_id, draft_status=SectionStatus.GENERANDO_BORRADOR.value, iterations=iteration)
        draft = generators.generate(
            department_id,
            state["brief"],
            state.get("knowledge", []),
            previous_draft=state.get("draft"),
            feedback=state.get("feedback"),
        )
        logger.info(
            "ticket=%s node=%s iteration=%s words=%s",
            state["ticket_id"],
            generator_node_name(department_id),
            iteration,
            len(draft.split()),
        )
        _report(config, department_id, draft_status=SectionStatus.EN_EVALUACION.value, draft_content=draft)
        return {"iteration": iteration, "draft": draft}

    generator.__name__ = generator_node_name(department_id)
    return generator


def readability_evaluator(state: SectionState) -> dict[str, Any]:
    return {"readability": evaluators.as_json(evaluators.evaluate_readability(state["draft"]))}


def relevance_evaluator(state: SectionState) -> dict[str, Any]:
    result = evaluators.evaluate_relevance(
        state["department_id"], state["draft"], state["brief"]["department"]["key_aspects"]
    )
    return {"relevance": evaluators.as_json(result)}


def compliance_evaluator(state: SectionState) -> dict[str, Any]:
    result = evaluators.evaluate_compliance(state["department_id"], state["draft"], state["brief"].get("currency"))
    return {"compliance": evaluators.as_json(result)}


def judge(state: SectionState, config: RunnableConfig) -> dict[str, Any]:
    department_id, iteration = state["department_id"], state["iteration"]
    result = evaluators.judge(
        state["ticket_id"],
        department_id,
        iteration,
        evaluators.ReadabilityResult.model_validate(state["readability"]),
        evaluators.RelevanceResult.model_validate(state["relevance"]),
        evaluators.ComplianceResult.model_validate(state["compliance"]),
    )
    if result.overall_pass:
        status = SectionStatus.EVALUACION_SUPERADA
    elif iteration >= state["max_iterations"]:
        status = SectionStatus.NEEDS_HUMAN_REVIEW
    else:
        status = SectionStatus.GENERANDO_BORRADOR
    evaluation = evaluators.as_json(result)
    entry = {"iteration": iteration, "draft_content": state["draft"], "evaluation": evaluation}
    history = [*state.get("history", []), entry]
    log = logger.warning if status is SectionStatus.NEEDS_HUMAN_REVIEW else logger.info
    log(
        "ticket=%s node=judge department=%s iteration=%s/%s readability=%s relevance=%s compliance=%s rules=%s "
        "status=%s",
        state["ticket_id"],
        department_id,
        iteration,
        state["max_iterations"],
        result.readability.passed,
        result.relevance.passed,
        result.compliance.passed,
        result.compliance.rule_ids,
        status.value,
    )
    final_status = status if status is not SectionStatus.GENERANDO_BORRADOR else SectionStatus.EN_EVALUACION
    _report(
        config,
        department_id,
        draft_status=final_status.value,
        evaluation_results=evaluation,
        evaluation_history=history,
    )
    return {
        "evaluation": evaluation,
        "feedback": result.feedback_for_generator,
        "history": [entry],
        "status": status.value,
    }


def route_after_judge(state: SectionState) -> str:
    if state["status"] == SectionStatus.GENERANDO_BORRADOR.value:
        return generator_node_name(state["department_id"])
    return END


def define_section_graph(department_id: str) -> StateGraph:
    generator_name = generator_node_name(department_id)
    builder = StateGraph(SectionState)
    builder.add_node(RETRIEVE_KNOWLEDGE, retrieve_knowledge)
    builder.add_node(generator_name, make_generator(department_id))
    builder.add_node(READABILITY_EVALUATOR, readability_evaluator)
    builder.add_node(RELEVANCE_EVALUATOR, relevance_evaluator)
    builder.add_node(COMPLIANCE_EVALUATOR, compliance_evaluator)
    builder.add_node(JUDGE, judge)

    builder.add_edge(START, RETRIEVE_KNOWLEDGE)
    builder.add_edge(RETRIEVE_KNOWLEDGE, generator_name)
    for evaluator in EVALUATORS:
        builder.add_edge(generator_name, evaluator)
    # `judge` espera a los tres evaluadores de la misma iteración.
    builder.add_edge(list(EVALUATORS), JUDGE)
    builder.add_conditional_edges(JUDGE, route_after_judge, [generator_name, END])
    return builder


section_graphs: dict[str, CompiledStateGraph] = {
    department_id: define_section_graph(department_id).compile() for department_id in DEPARTMENTS
}


# --- Grafo principal ---------------------------------------------------------------------------


def dispatch_sections(state: ResponseState) -> list[Send]:
    return [
        Send(
            section_node_name(workstream["department_id"]),
            SectionState(
                ticket_id=state["ticket_id"],
                department_id=workstream["department_id"],
                brief={**state["shared"], "department": workstream},
                max_iterations=state["max_iterations"],
                history=[],
            ),
        )
        for workstream in state["workstreams"]
    ]


def make_section(department_id: str):
    def section(payload: SectionState, config: RunnableConfig) -> dict[str, Any]:
        # Cada iteración son 3 pasos (generador, evaluadores, juez) más la búsqueda inicial.
        limit = 3 * payload["max_iterations"] + 10
        result = section_graphs[department_id].invoke(payload, {**config, "recursion_limit": limit})
        return {
            "sections": [
                {
                    "department_id": department_id,
                    "draft_status": result["status"],
                    "iterations": result["iteration"],
                    "draft_content": result["draft"],
                    "evaluation_results": result["evaluation"],
                    "evaluation_history": result["history"],
                }
            ]
        }

    section.__name__ = section_node_name(department_id)
    return section


def define_graph() -> StateGraph:
    builder = StateGraph(ResponseState)
    section_names = [section_node_name(department_id) for department_id in DEPARTMENTS]
    for department_id in DEPARTMENTS:
        builder.add_node(section_node_name(department_id), make_section(department_id))
    builder.add_conditional_edges(START, dispatch_sections, section_names)
    for name in section_names:
        builder.add_edge(name, END)
    return builder


graph: CompiledStateGraph = define_graph().compile()


def run_graph(
    ticket_id: str,
    shared: dict[str, Any],
    workstreams: list[dict[str, Any]],
    max_iterations: int,
    progress: ProgressSink | None = None,
) -> ResponseState:
    order = list(DEPARTMENTS)
    state = graph.invoke(
        {
            "ticket_id": ticket_id,
            "shared": shared,
            "workstreams": workstreams,
            "max_iterations": max_iterations,
            "sections": [],
        },
        {"configurable": {"progress": progress}},
    )
    state["sections"] = sorted(state["sections"], key=lambda section: order.index(section["department_id"]))
    return state
