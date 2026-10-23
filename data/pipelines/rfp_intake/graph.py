"""Grafo LangGraph dedicado `rfp_intake` (no comparte nodos con el grafo de CX de `services/support_agent`).

    START → convert_document → classify_document ─┬─ (no es RFP) → discard → END
                                                  └─ (RFP) → extract_metadata → orchestrate
    orchestrate ─┬─ Send por departamento activo → warehouse_worker / lastmile_worker / reverse_worker (en paralelo)
                 └─ (ningún departamento aplica) → synthesize
    *_worker → synthesize → END

- `convert_document` pasa el PDF a Markdown antes de que lo lea ningún agente.
- Cada worker recibe por `Send` solo su carga (`WorkerInput`): metadatos, tarea y párrafos; no el estado entero.
  Sus secciones se acumulan con un reducer, así que el orden de llegada no importa.
- El grafo no escribe en la base de datos: `runner.py` persiste el resultado en una sola transacción, de modo que
  un fallo a mitad no deja un ticket a medio escribir.
"""

from __future__ import annotations

import logging
import operator
from dataclasses import asdict
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from data.pipelines.rfp_intake import classifier, document, extraction, orchestrator, synthesizer, workers
from data.pipelines.rfp_intake.departments import DEPARTMENTS


logger = logging.getLogger("trackflow.rfp_intake")

CONVERT_DOCUMENT = "convert_document"
CLASSIFY_DOCUMENT = "classify_document"
DISCARD = "discard"
EXTRACT_METADATA = "extract_metadata"
ORCHESTRATE = "orchestrate"
SYNTHESIZE = "synthesize"


def worker_node_name(department_id: str) -> str:
    return f"{department_id}_worker"


class IntakeState(TypedDict, total=False):
    ticket_id: str
    pdf_path: str
    markdown: str
    paragraphs: list[str]
    classification: dict[str, Any]
    metadata: dict[str, Any]
    readability: dict[str, Any]
    assignments: list[dict[str, Any]]
    out_of_scope: list[str]
    # Una sección por worker; el reducer las acumula aunque lleguen en paralelo.
    sections: Annotated[list[dict[str, Any]], operator.add]
    synthesis: dict[str, Any]


class WorkerInput(TypedDict):
    ticket_id: str
    department_id: str
    focus: str
    metadata: dict[str, Any]
    excerpts: list[str]


def convert_document(state: IntakeState) -> dict[str, Any]:
    markdown = document.pdf_to_markdown(state["pdf_path"])
    paragraphs = document.split_paragraphs(markdown)
    logger.info("ticket=%s node=convert_document chars=%s paragraphs=%s", state["ticket_id"], len(markdown), len(paragraphs))
    return {"markdown": markdown, "paragraphs": paragraphs}


def classify_document(state: IntakeState) -> dict[str, Any]:
    result = classifier.classify(state["markdown"])
    logger.info(
        "ticket=%s node=classify_document is_rfp=%s type=%s confidence=%.2f",
        state["ticket_id"],
        result.is_rfp,
        result.document_type,
        result.confidence,
    )
    return {
        "classification": {
            "is_rfp": result.is_rfp,
            "document_type": result.document_type,
            "confidence": result.confidence,
            "reason": result.reason,
        }
    }


def route_after_classification(state: IntakeState) -> str:
    return EXTRACT_METADATA if state["classification"]["is_rfp"] else DISCARD


def discard(state: IntakeState) -> dict[str, Any]:
    logger.info("ticket=%s node=discard reason=%r", state["ticket_id"], state["classification"]["reason"])
    return {}


def extract_metadata(state: IntakeState) -> dict[str, Any]:
    metadata = extraction.extract_metadata(state["markdown"])
    metrics = document.readability_metrics(state["markdown"])
    logger.info(
        "ticket=%s node=extract_metadata country=%s currency=%s services=%s volume=%s tokens=%s",
        state["ticket_id"],
        metadata["client_country"],
        metadata["currency"],
        metadata["services_requested"],
        metadata["monthly_volume"],
        metrics.estimated_tokens,
    )
    return {"metadata": metadata, "readability": asdict(metrics)}


def orchestrate(state: IntakeState) -> dict[str, Any]:
    result = orchestrator.plan(state["metadata"], state["paragraphs"])
    logger.info(
        "ticket=%s node=orchestrate departments=%s out_of_scope=%s",
        state["ticket_id"],
        [item["department_id"] for item in result["assignments"]],
        len(result["out_of_scope"]),
    )
    return {"assignments": result["assignments"], "out_of_scope": result["out_of_scope"]}


def dispatch_workers(state: IntakeState) -> list[Send] | str:
    if not state["assignments"]:
        logger.warning("ticket=%s ningún departamento aplica: el synthesizer lo explica a Ventas.", state["ticket_id"])
        return SYNTHESIZE
    paragraphs = state["paragraphs"]
    return [
        Send(
            worker_node_name(item["department_id"]),
            WorkerInput(
                ticket_id=state["ticket_id"],
                department_id=item["department_id"],
                focus=item["focus"],
                metadata=state["metadata"],
                excerpts=[paragraphs[index - 1] for index in item["paragraph_ids"]],
            ),
        )
        for item in state["assignments"]
    ]


def make_worker(department_id: str):
    def worker(payload: WorkerInput) -> dict[str, Any]:
        section = workers.analyze(department_id, payload["focus"], payload["metadata"], payload["excerpts"])
        logger.info(
            "ticket=%s node=%s key_aspects=%s open_questions=%s",
            payload["ticket_id"],
            worker_node_name(department_id),
            len(section["key_aspects"]),
            len(section["open_questions"]),
        )
        return {"sections": [section]}

    worker.__name__ = worker_node_name(department_id)
    return worker


def synthesize(state: IntakeState) -> dict[str, Any]:
    order = list(DEPARTMENTS)
    sections = sorted(state.get("sections", []), key=lambda section: order.index(section["department_id"]))
    synthesis = synthesizer.synthesize(state["metadata"], sections, state["out_of_scope"])
    logger.info("ticket=%s node=synthesize conflicts=%s", state["ticket_id"], len(synthesis["conflicts"]))
    return {"synthesis": synthesis}


def define_graph() -> StateGraph:
    builder = StateGraph(IntakeState)
    builder.add_node(CONVERT_DOCUMENT, convert_document)
    builder.add_node(CLASSIFY_DOCUMENT, classify_document)
    builder.add_node(DISCARD, discard)
    builder.add_node(EXTRACT_METADATA, extract_metadata)
    builder.add_node(ORCHESTRATE, orchestrate)
    worker_names = [worker_node_name(department_id) for department_id in DEPARTMENTS]
    for department_id in DEPARTMENTS:
        builder.add_node(worker_node_name(department_id), make_worker(department_id))
    builder.add_node(SYNTHESIZE, synthesize)

    builder.add_edge(START, CONVERT_DOCUMENT)
    builder.add_edge(CONVERT_DOCUMENT, CLASSIFY_DOCUMENT)
    builder.add_conditional_edges(
        CLASSIFY_DOCUMENT, route_after_classification, {EXTRACT_METADATA: EXTRACT_METADATA, DISCARD: DISCARD}
    )
    builder.add_edge(DISCARD, END)
    builder.add_edge(EXTRACT_METADATA, ORCHESTRATE)
    builder.add_conditional_edges(ORCHESTRATE, dispatch_workers, [*worker_names, SYNTHESIZE])
    for name in worker_names:
        builder.add_edge(name, SYNTHESIZE)
    builder.add_edge(SYNTHESIZE, END)
    return builder


graph: CompiledStateGraph = define_graph().compile()


def run_graph(ticket_id: str, pdf_path: str) -> IntakeState:
    return graph.invoke({"ticket_id": ticket_id, "pdf_path": pdf_path, "sections": []})
