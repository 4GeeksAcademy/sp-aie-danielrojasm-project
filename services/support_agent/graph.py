"""Definición, validación y compilación del grafo del agente.

    START → receive_question ─┬─ (pregunta vacía) ──→ reject_question → END
                              └─ (hay pregunta) ────→ retrieve ─┬─ (hay contexto) ──→ generate_answer → END
                                                                └─ (sin contexto) ──→ no_information → END

`compile_graph()` se ejecuta al importar este módulo, antes de cualquier corrida. A la validación de LangGraph
(aristas hacia nodos que no existen, falta de entrada) le añade la que LangGraph no hace: todo nodo tiene que ser
alcanzable desde START y tener un camino hasta END. Cualquier fallo es un `AgentGraphError` con el motivo.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from services.support_agent import nodes
from services.support_agent.state import AgentState


class AgentGraphError(RuntimeError):
    """El grafo del agente tiene un error estructural y no se puede compilar."""


def define_graph() -> StateGraph:
    builder = StateGraph(AgentState)
    builder.add_node(nodes.RECEIVE_QUESTION, nodes.receive_question)
    builder.add_node(nodes.REJECT_QUESTION, nodes.reject_question)
    builder.add_node(nodes.RETRIEVE, nodes.retrieve)
    builder.add_node(nodes.GENERATE_ANSWER, nodes.generate_answer)
    builder.add_node(nodes.NO_INFORMATION, nodes.no_information)

    builder.add_edge(START, nodes.RECEIVE_QUESTION)
    builder.add_conditional_edges(
        nodes.RECEIVE_QUESTION,
        nodes.route_after_question,
        {nodes.REJECT_QUESTION: nodes.REJECT_QUESTION, nodes.RETRIEVE: nodes.RETRIEVE},
    )
    builder.add_conditional_edges(
        nodes.RETRIEVE,
        nodes.route_after_retrieve,
        {nodes.GENERATE_ANSWER: nodes.GENERATE_ANSWER, nodes.NO_INFORMATION: nodes.NO_INFORMATION},
    )
    builder.add_edge(nodes.REJECT_QUESTION, END)
    builder.add_edge(nodes.GENERATE_ANSWER, END)
    builder.add_edge(nodes.NO_INFORMATION, END)
    return builder


def compile_graph(builder: StateGraph, checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    try:
        compiled = builder.compile(checkpointer=checkpointer)
    except ValueError as error:
        raise AgentGraphError(f"El grafo del agente no compila: {error}") from error
    _check_every_node_is_connected(builder)
    return compiled


def _check_every_node_is_connected(builder: StateGraph) -> None:
    # Se valida sobre las aristas declaradas: el grafo dibujable de LangGraph une a END cualquier nodo sin salida.
    names = set(builder.nodes) | {START, END}
    successors: dict[str, set[str]] = {node: set() for node in names}
    predecessors: dict[str, set[str]] = {node: set() for node in names}
    edges = set(builder.edges)
    for source, branches in builder.branches.items():
        for branch in branches.values():
            if branch.ends is None:
                raise AgentGraphError(
                    f"El grafo del agente no compila: la arista condicional de {source} necesita sus destinos explícitos."
                )
            edges.update((source, target) for target in branch.ends.values())
    for source, target in edges:
        successors[source].add(target)
        predecessors[target].add(source)

    from_start = _reachable(START, successors)
    to_end = _reachable(END, predecessors)
    unreachable = sorted(set(builder.nodes) - from_start)
    dead_ends = sorted(set(builder.nodes) - to_end)
    problems = []
    if unreachable:
        problems.append(f"nodos sin conexión desde START: {', '.join(unreachable)}")
    if dead_ends:
        problems.append(f"nodos sin camino hasta END: {', '.join(dead_ends)}")
    if problems:
        raise AgentGraphError(f"El grafo del agente no compila: {'; '.join(problems)}.")


def _reachable(origin: str, neighbours: dict[str, set[str]]) -> set[str]:
    seen = {origin}
    pending = [origin]
    while pending:
        for node in neighbours.get(pending.pop(), ()):
            if node not in seen:
                seen.add(node)
                pending.append(node)
    return seen


# Checkpoint en memoria por transición (`thread_id` = `run_id`). Lo que sobrevive al proceso es el trace JSON,
# que incluye el historial de checkpoints de cada corrida (ver `runner.py`).
graph = compile_graph(define_graph(), checkpointer=InMemorySaver())
