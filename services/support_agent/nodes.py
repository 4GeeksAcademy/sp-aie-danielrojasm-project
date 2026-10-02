"""Nodos del agente (una responsabilidad cada uno) y las condiciones de salida que deciden el siguiente.

Los nodos `retrieve` y `generate_answer` llaman a las funciones de `data/pipelines/rag.py` por separado; ningún nodo
usa `query()`, para que la recuperación se ejecute una sola vez y quede visible en el trace.
"""

from __future__ import annotations

from typing import Literal

from data.pipelines import rag
from services.support_agent.state import AgentState


RECEIVE_QUESTION = "receive_question"
REJECT_QUESTION = "reject_question"
RETRIEVE = "retrieve"
GENERATE_ANSWER = "generate_answer"
NO_INFORMATION = "no_information"

EMPTY_QUESTION_ERROR = "La pregunta está vacía: escribe qué quiere saber el cliente."

NO_INFORMATION_ANSWER = (
    "No tengo información sobre eso en la base de conocimiento de TrackFlow. Antes de responder al cliente, "
    "confírmalo con el equipo responsable.\nFuente: sin información en la base de conocimiento"
)


def receive_question(state: AgentState) -> AgentState:
    """Normaliza la pregunta de entrada (sin espacios sobrantes)."""
    return {"question": (state.get("question") or "").strip()}


def reject_question(state: AgentState) -> AgentState:
    """Termina la corrida sin recuperar nada: no hay pregunta que responder."""
    return {"error": EMPTY_QUESTION_ERROR}


def retrieve(state: AgentState) -> AgentState:
    """Payloads de la base de conocimiento por encima de `min_score` (`data.pipelines.rag.retrieve`)."""
    return {"context": rag.retrieve(state["question"])}


def generate_answer(state: AgentState) -> AgentState:
    """Respuesta del modelo de generación a partir del contexto que ya recuperó el nodo `retrieve`."""
    return {"answer": rag.generate_answer(state["question"], state["context"])}


def no_information(state: AgentState) -> AgentState:
    """Respuesta honesta sin llamar al modelo: ningún fragmento superó el umbral."""
    return {"answer": NO_INFORMATION_ANSWER}


def route_after_question(state: AgentState) -> Literal["reject_question", "retrieve"]:
    return REJECT_QUESTION if not state["question"] else RETRIEVE


def route_after_retrieve(state: AgentState) -> Literal["generate_answer", "no_information"]:
    return GENERATE_ANSWER if state["context"] else NO_INFORMATION
