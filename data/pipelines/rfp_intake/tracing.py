"""Traza por nodo de los tres grafos de RFPs: qué agente hizo qué, con qué entrada y salida, y en qué orden.

Cada nodo se registra con `traced(...)` al construir el grafo. La entrada `trace` del estado (con reducer de suma)
acumula una entrada por ejecución de nodo:

    {"part": "parte_3", "node": "warehouse_human_review", "agent": "Ana Whitfield", "department_id": "warehouse",
     "input": {...}, "output": {...}, "timestamp": "<ISO 8601 UTC: cuándo terminó>", "duration_ms": 12}

`input` y `output` son vistas compactas (cadenas largas recortadas, sin el Markdown del documento ni el PDF): sirven
para saber qué pasó sin duplicar los datos que ya guardan las tablas. Los runners guardan la traza en
`rfp_tickets.trace`; la Parte 3, que se pausa, la escribe en cuanto termina cada nodo a través del sink de
`config["configurable"]["trace_sink"]`.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig


MAX_TEXT = 240
MAX_ITEMS = 12
# Claves que nunca se copian a la traza: el documento entero y los borradores ya están en sus tablas.
OMITTED_KEYS = frozenset({"markdown", "paragraphs", "trace", "history", "evaluation_history"})


class TraceSink(Protocol):
    def trace(self, entry: dict[str, Any]) -> None: ...


def compact(value: Any, depth: int = 0) -> Any:
    """Vista recortada de un valor para la traza: textos de como mucho `MAX_TEXT` caracteres y listas cortas."""
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else f"{value[:MAX_TEXT]}… ({len(value)} caracteres)"
    if isinstance(value, dict):
        if depth >= 3:
            return f"{{{len(value)} claves}}"
        return {key: compact(item, depth + 1) for key, item in value.items() if key not in OMITTED_KEYS}
    if isinstance(value, (list, tuple)):
        if depth >= 3:
            return f"[{len(value)} elementos]"
        items = [compact(item, depth + 1) for item in value[:MAX_ITEMS]]
        return items + [f"… {len(value) - MAX_ITEMS} más"] if len(value) > MAX_ITEMS else items
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def entry(
    part: str,
    node: str,
    agent: str,
    node_input: Any,
    node_output: Any,
    department_id: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    return {
        "part": part,
        "node": node,
        "agent": agent,
        "department_id": department_id,
        "input": compact(node_input),
        "output": compact(node_output),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
    }


def traced(
    part: str,
    node: str,
    agent: str,
    function: Callable[..., dict[str, Any] | None],
    *,
    department_id: str | None = None,
    input_keys: tuple[str, ...] | None = None,
) -> Callable[[Any, RunnableConfig], dict[str, Any]]:
    """Envuelve un nodo para que añada su entrada de traza al estado (y al sink, si lo hay).

    `input_keys` limita la entrada registrada a esas claves del estado; sin ella se registra el estado compacto.
    Una excepción (incluida la de `interrupt`) se propaga sin registrar nada: el nodo no terminó.
    """
    takes_config = len(inspect.signature(function).parameters) > 1

    def node_function(state: Any, config: RunnableConfig) -> dict[str, Any]:
        started = time.perf_counter()
        output = (function(state, config) if takes_config else function(state)) or {}
        node_input = {key: state.get(key) for key in input_keys} if input_keys is not None else state
        record = entry(
            part,
            node,
            agent,
            node_input,
            output,
            department_id=department_id or state.get("department_id"),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        sink = (config.get("configurable") or {}).get("trace_sink")
        if sink is not None:
            sink.trace(record)
        return {**output, "trace": [*output.get("trace", []), record]}

    node_function.__name__ = node
    return node_function


def ordered(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entradas en orden de ejecución (las ramas paralelas llegan al estado cuando terminan, no cuando empiezan)."""
    return sorted(entries, key=lambda item: item["timestamp"])
