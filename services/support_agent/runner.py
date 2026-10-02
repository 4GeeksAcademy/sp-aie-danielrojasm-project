"""Ejecución trazada del grafo: `run_agent()` para una pregunta nueva y `resume_run()` para retomar una corrida fallida.

Cada corrida usa su `run_id` como `thread_id` del checkpointer. El trace se escribe siempre, también cuando un nodo
falla; en ese caso el hilo se conserva en el checkpointer para poder retomarlo desde el último checkpoint sin repetir
los nodos que ya terminaron. Las corridas completadas liberan su hilo: su historial ya está en el trace.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from services.support_agent.graph import graph as default_graph
from services.support_agent.state import AgentState
from services.support_agent.tracing import TRACE_VERSION, load_trace, trace_path, write_trace


logger = logging.getLogger("trackflow.agent")


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    state: AgentState
    trace_path: Path


class AgentRunError(RuntimeError):
    """Un nodo falló. Conserva la excepción original como `__cause__`."""

    def __init__(self, run_id: str, node: str | None, trace_path: Path):
        super().__init__(f"La corrida {run_id} del agente falló en el nodo {node or 'desconocido'}.")
        self.run_id = run_id
        self.node = node
        self.trace_path = trace_path


def run_agent(
    question: str,
    *,
    compiled: CompiledStateGraph | None = None,
    directory: Path | None = None,
    run_id: str | None = None,
) -> AgentRun:
    run_id = run_id or uuid.uuid4().hex
    trace = _new_trace(run_id, question)
    return _execute(compiled or default_graph, {"question": question}, trace, directory)


def resume_run(
    run_id: str, *, compiled: CompiledStateGraph | None = None, directory: Path | None = None
) -> AgentRun:
    """Continúa una corrida fallida desde su último checkpoint (los nodos ya terminados no se repiten)."""
    trace = load_trace(trace_path(run_id, directory))
    trace["resumed"] = trace.get("resumed", 0) + 1
    trace.pop("error", None)
    return _execute(compiled or default_graph, None, trace, directory)


def _new_trace(run_id: str, question: str) -> dict[str, Any]:
    return {
        "trace_version": TRACE_VERSION,
        "run_id": run_id,
        "question": question,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "status": "running",
        "steps": [],
    }


def _execute(
    compiled: CompiledStateGraph,
    graph_input: AgentState | None,
    trace: dict[str, Any],
    directory: Path | None,
) -> AgentRun:
    run_id = trace["run_id"]
    config = {"configurable": {"thread_id": run_id}}
    started = last = time.perf_counter()
    try:
        for update in compiled.stream(graph_input, config, stream_mode="updates"):
            for node, output in update.items():
                now = time.perf_counter()
                trace["steps"].append(
                    {
                        "order": len(trace["steps"]) + 1,
                        "node": node,
                        "duration_ms": round((now - last) * 1000, 1),
                        "output": output,
                    }
                )
                last = now
    except Exception as error:
        snapshot = compiled.get_state(config)
        failed_node = snapshot.next[0] if snapshot.next else None
        trace["error"] = {"node": failed_node, "type": type(error).__name__, "message": str(error)}
        path = _finish(compiled, config, trace, "failed", started, directory)
        logger.error(
            "agent_run run_id=%s status=failed node=%s error=%s trace=%s",
            run_id,
            failed_node,
            type(error).__name__,
            path,
        )
        raise AgentRunError(run_id, failed_node, path) from error

    path = _finish(compiled, config, trace, "completed", started, directory)
    state: AgentState = trace["final_state"]
    compiled.checkpointer.delete_thread(run_id)
    logger.info(
        "agent_run run_id=%s status=completed nodes=%s duration_ms=%.0f trace=%s",
        run_id,
        ">".join(step["node"] for step in trace["steps"]),
        trace["duration_ms"],
        path,
    )
    return AgentRun(run_id=run_id, state=state, trace_path=path)


def _finish(
    compiled: CompiledStateGraph,
    config: dict[str, Any],
    trace: dict[str, Any],
    status: str,
    started: float,
    directory: Path | None,
) -> Path:
    trace["status"] = status
    trace["duration_ms"] = round(trace.get("duration_ms", 0) + (time.perf_counter() - started) * 1000, 1)
    trace["final_state"] = dict(compiled.get_state(config).values)
    trace["checkpoints"] = [
        {
            "step": snapshot.metadata.get("step"),
            "source": snapshot.metadata.get("source"),
            "next": list(snapshot.next),
            "checkpoint_id": snapshot.config["configurable"]["checkpoint_id"],
            "values": dict(snapshot.values),
        }
        for snapshot in reversed(list(compiled.get_state_history(config)))
    ]
    return write_trace(trace, directory)
