"""Traces de las corridas del agente: un JSON por corrida en `AGENT_TRACE_DIR` (por defecto `data/raw/agent_traces/`).

Formato (`trace_version` 1):

- `run_id`, `question`, `started_at`, `duration_ms`, `status` (`completed` | `failed`).
- `steps`: nodos en el orden en que se ejecutaron, con `order`, `node`, `duration_ms` y `output` (lo que el nodo
  escribió en el estado).
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
TRACE_VERSION = 1


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
