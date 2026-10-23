"""Definición, validación y compilación del grafo del agente.

    START → receive_question ─┬─ (pregunta vacía) → reject_question → END
                              └─ (hay pregunta) → input_guard ─┬─ (cambio de instrucciones, uso personal,
                                                               │   pedido ajeno a la sesión) → guardrail_refusal → END
                                                               └─ (se responde) → load_pending_proposal

    load_pending_proposal ─┬─ (propuesta pendiente) → resolve_proposal
                           ├─ (small talk) → small_talk_reply
                           └─ (ninguna) → recall_memory

    resolve_proposal ─┬─ (el mensaje también pregunta algo) → recall_memory, o small_talk_reply si es small talk
                      └─ (solo respondía a la propuesta) → END

    recall_memory → route_question ─┬─ (cita tickets) → lookup_tickets
                                    └─ (sin tickets) → retrieve

    lookup_tickets ─┬─ (también necesita la base de conocimiento) → retrieve
                    ├─ (algún ticket confirmado) → generate_answer
                    └─ (ningún ticket confirmado) → ticket_fallback

    retrieve ─┬─ (hay contexto o tickets confirmados) → generate_answer
              ├─ (sin contexto, tickets sin confirmar) → ticket_fallback
              ├─ (sin contexto ni tickets, con memoria recordada) → generate_answer
              └─ (sin contexto, tickets ni memoria) → no_information

    generate_answer / no_information / ticket_fallback / small_talk_reply → output_guard

    output_guard ─┬─ (el modelo propuso algo que recordar) → propose_memory → END
                  └─ (nada que recordar) → END

`compile_graph()` se ejecuta al importar este módulo, antes de cualquier corrida. A la validación de LangGraph
(aristas hacia nodos que no existen, falta de entrada) le añade la que LangGraph no hace: todo nodo tiene que ser
alcanzable desde START y tener un camino hasta END. Cualquier fallo es un `AgentGraphError` con el motivo.
"""

from __future__ import annotations

from collections.abc import Callable

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
    for name, node in (
        (nodes.RECEIVE_QUESTION, nodes.receive_question),
        (nodes.REJECT_QUESTION, nodes.reject_question),
        (nodes.INPUT_GUARD, nodes.input_guard),
        (nodes.GUARDRAIL_REFUSAL, nodes.guardrail_refusal),
        (nodes.SMALL_TALK_REPLY, nodes.small_talk_reply),
        (nodes.LOAD_PENDING_PROPOSAL, nodes.load_pending_proposal),
        (nodes.RESOLVE_PROPOSAL, nodes.resolve_proposal),
        (nodes.RECALL_MEMORY, nodes.recall_memory),
        (nodes.ROUTE_QUESTION, nodes.route_question),
        (nodes.LOOKUP_TICKETS, nodes.lookup_tickets),
        (nodes.RETRIEVE, nodes.retrieve),
        (nodes.GENERATE_ANSWER, nodes.generate_answer),
        (nodes.TICKET_FALLBACK, nodes.ticket_fallback),
        (nodes.NO_INFORMATION, nodes.no_information),
        (nodes.PROPOSE_MEMORY, nodes.propose_memory),
        (nodes.OUTPUT_GUARD, nodes.output_guard),
    ):
        builder.add_node(name, node)

    builder.add_edge(START, nodes.RECEIVE_QUESTION)
    _add_routes(builder, nodes.RECEIVE_QUESTION, nodes.route_after_question, nodes.REJECT_QUESTION, nodes.INPUT_GUARD)
    _add_routes(
        builder,
        nodes.INPUT_GUARD,
        nodes.route_after_input_guard,
        nodes.GUARDRAIL_REFUSAL,
        nodes.LOAD_PENDING_PROPOSAL,
    )
    _add_routes(
        builder,
        nodes.LOAD_PENDING_PROPOSAL,
        nodes.route_after_pending,
        nodes.RESOLVE_PROPOSAL,
        nodes.SMALL_TALK_REPLY,
        nodes.RECALL_MEMORY,
    )
    _add_routes(
        builder, nodes.RESOLVE_PROPOSAL, nodes.route_after_resolution, nodes.SMALL_TALK_REPLY, nodes.RECALL_MEMORY, END
    )
    builder.add_edge(nodes.RECALL_MEMORY, nodes.ROUTE_QUESTION)
    _add_routes(builder, nodes.ROUTE_QUESTION, nodes.route_after_plan, nodes.LOOKUP_TICKETS, nodes.RETRIEVE)
    _add_routes(
        builder,
        nodes.LOOKUP_TICKETS,
        nodes.route_after_lookup,
        nodes.RETRIEVE,
        nodes.GENERATE_ANSWER,
        nodes.TICKET_FALLBACK,
    )
    _add_routes(
        builder,
        nodes.RETRIEVE,
        nodes.route_after_retrieve,
        nodes.GENERATE_ANSWER,
        nodes.TICKET_FALLBACK,
        nodes.NO_INFORMATION,
    )
    for answered in (nodes.GENERATE_ANSWER, nodes.NO_INFORMATION, nodes.TICKET_FALLBACK, nodes.SMALL_TALK_REPLY):
        builder.add_edge(answered, nodes.OUTPUT_GUARD)
    _add_routes(builder, nodes.OUTPUT_GUARD, nodes.route_after_answer, nodes.PROPOSE_MEMORY, END)
    for final in (nodes.REJECT_QUESTION, nodes.GUARDRAIL_REFUSAL, nodes.PROPOSE_MEMORY):
        builder.add_edge(final, END)
    return builder


def _add_routes(builder: StateGraph, source: str, condition: Callable[[AgentState], str], *targets: str) -> None:
    builder.add_conditional_edges(source, condition, {target: target for target in targets})


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
