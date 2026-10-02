"""Observabilidad de los guardrails: un log por activación y contadores para el resumen de una sesión de pruebas.

Cada vez que una capa bloquea, reconduce, limpia o corrige algo, `record()` escribe una línea en el log
`trackflow.guardrails` con el guardrail, el tipo de fallo (`structural`, `content`, `security`), la acción y el
motivo, y suma uno a los contadores del proceso. Nunca registra el mensaje del usuario ni el texto retirado: solo la
categoría. `summary()` resume los contadores desde que arrancó el proceso o desde el último `reset()`;
`GET /agent/guardrails/summary` lo expone.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel


logger = logging.getLogger("trackflow.guardrails")

FailureType = Literal["structural", "content", "security"]
Action = Literal["block", "redirect", "constrain", "sanitize", "redact", "repair"]


class GuardrailEvent(BaseModel):
    guardrail: str
    failure_type: FailureType
    action: Action
    reason: str


class _Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._since = datetime.now(timezone.utc)
            self._counts: Counter[tuple[str, str, str]] = Counter()

    def add(self, event: GuardrailEvent) -> None:
        with self._lock:
            self._counts[(event.guardrail, event.failure_type, event.action)] += 1

    def summary(self) -> dict[str, Any]:
        with self._lock:
            counts = dict(self._counts)
            since = self._since
        by_guardrail: Counter[str] = Counter()
        by_failure_type: Counter[str] = Counter()
        by_action: Counter[str] = Counter()
        for (guardrail, failure_type, action), count in counts.items():
            by_guardrail[guardrail] += count
            by_failure_type[failure_type] += count
            by_action[action] += count
        return {
            "since": since,
            "total": sum(counts.values()),
            "by_guardrail": dict(sorted(by_guardrail.items())),
            "by_failure_type": dict(sorted(by_failure_type.items())),
            "by_action": dict(sorted(by_action.items())),
        }


_stats = _Stats()


def record(event: GuardrailEvent, *, run_id: str | None = None, conversation_id: str | None = None) -> dict[str, Any]:
    """Registra la activación (log + contador) y la devuelve serializada para el estado y el trace."""
    _stats.add(event)
    logger.warning(
        "guardrail=%s failure_type=%s action=%s reason=%s run_id=%s conversation_id=%s",
        event.guardrail,
        event.failure_type,
        event.action,
        event.reason,
        run_id or "-",
        conversation_id or "-",
    )
    return event.model_dump()


def summary() -> dict[str, Any]:
    return _stats.summary()


def reset() -> None:
    _stats.reset()
