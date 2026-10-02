"""Traces de las corridas del agente: un JSON por corrida en `AGENT_TRACE_DIR` (por defecto `data/raw/agent_traces/`).

Formato (`trace_version` 2):

- `run_id`, `question`, `started_at`, `duration_ms`, `status` (`completed` | `failed`).
- `sources_used`: fuentes consultadas en orden (`incidents_tool` = gestor de incidencias, `rag` = base de
  conocimiento); vacío si la corrida no consultó ninguna.
- `steps`: nodos en el orden en que se ejecutaron, con `order`, `node`, `duration_ms` y `output` (lo que el nodo
  escribió en el estado; el de `route_question` es la decisión de fuentes y quién la tomó).
- `final_state`: estado al terminar (`question`, `context`, `answer` o `error`).
- `checkpoints`: un checkpoint por transición (`step`, `source`, `next`, `checkpoint_id`, `values`), del más antiguo
  al más reciente.
- `error`: solo si falló (`node`, `type`, `message`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TRACE_VERSION = 2

# Nodos que consultan una fuente de datos externa al grafo.
SOURCE_BY_NODE = {"lookup_tickets": "incidents_tool", "retrieve": "rag"}


def trace_dir() -> Path:
    return Path(os.getenv("AGENT_TRACE_DIR") or ROOT / "data" / "raw" / "agent_traces")


def trace_path(run_id: str, directory: Path | None = None) -> Path:
    return (directory or trace_dir()) / f"{run_id}.json"


def write_trace(trace: dict[str, Any], directory: Path | None = None) -> Path:
    path = trace_path(trace["run_id"], directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_trace(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def executed_nodes(trace: dict[str, Any]) -> list[str]:
    """Nombres de los nodos en el orden en que se ejecutaron."""
    return [step["node"] for step in trace["steps"]]


def sources_used(steps: list[dict[str, Any]]) -> list[str]:
    """Fuentes de datos consultadas, en el orden en que se consultaron (`incidents_tool`, `rag`)."""
    return [SOURCE_BY_NODE[step["node"]] for step in steps if step["node"] in SOURCE_BY_NODE]
