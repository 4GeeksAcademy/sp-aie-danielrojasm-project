"""Límite de turnos del agente por usuario: frena los bucles de coste (scripts, reintentos, interrupciones en cadena).

Cada turno que puede llamar al modelo consume una unidad de la ventana del usuario: `POST /agent/query` y los frames
`user_message` e `interrupt_requested` del chat (cada interrupción arranca una corrida nueva). Ventana fija de
`WINDOW_SECONDS` en Redis (`trackflow:agent_rate:<user_id>:<ventana>`, INCR + EXPIRE), compartida por todos los
workers de la API; el límite sale de `AGENT_RATE_LIMIT_PER_MINUTE` (por defecto `DEFAULT_LIMIT`).

Pasado el límite, el turno no se ejecuta: `429` con `Retry-After` en HTTP y `chat_error` en el chat. Cada rechazo deja
una línea en `trackflow.agent` y un evento `rate_limit` en `GET /agent/guardrails/summary`. Si Redis no responde, el
turno se permite y se registra el error: el soporte 24/7 no se cae por el limitador.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

import redis

from services.support_agent.guardrails import events
from services.support_agent.guardrails.events import GuardrailEvent


logger = logging.getLogger("trackflow.agent")

NAMESPACE = "trackflow:agent_rate"
DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_LIMIT = 10
WINDOW_SECONDS = 60

RATE_LIMITED_DETAIL = (
    "Has enviado demasiadas consultas al agente en poco tiempo (máximo {limit} por minuto). "
    "Espera {retry_after} s y vuelve a intentarlo."
)


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    count: int
    limit: int
    # Segundos hasta que se abre la siguiente ventana (valor de `Retry-After`).
    retry_after: int

    @property
    def detail(self) -> str:
        return RATE_LIMITED_DETAIL.format(limit=self.limit, retry_after=self.retry_after)


class AgentRateLimiter:
    def __init__(
        self,
        client: redis.Redis,
        limit: int | None = None,
        namespace: str = NAMESPACE,
        clock: Callable[[], float] = time.time,
    ):
        self.client = client
        self.limit = limit if limit is not None else configured_limit()
        self.namespace = namespace
        self.clock = clock

    def hit(self, user_id: str, *, channel: str) -> RateDecision:
        """Cuenta un turno del usuario. `channel` (`http` o `chat`) solo va al log."""
        now = self.clock()
        window = int(now // WINDOW_SECONDS)
        retry_after = max(1, WINDOW_SECONDS - int(now % WINDOW_SECONDS))
        key = f"{self.namespace}:{user_id}:{window}"
        try:
            pipeline = self.client.pipeline()
            pipeline.incr(key)
            pipeline.expire(key, WINDOW_SECONDS + 1)
            count, _ = pipeline.execute()
        except redis.RedisError as error:
            logger.error(
                "agent_rate_limit_unavailable user_id=%s channel=%s error=%s: el turno se permite sin límite.",
                user_id,
                channel,
                type(error).__name__,
            )
            return RateDecision(allowed=True, count=0, limit=self.limit, retry_after=0)
        decision = RateDecision(allowed=count <= self.limit, count=count, limit=self.limit, retry_after=retry_after)
        if not decision.allowed:
            logger.warning(
                "agent_rate_limited user_id=%s channel=%s count=%d limit=%d retry_after=%d",
                user_id,
                channel,
                count,
                self.limit,
                retry_after,
            )
            events.record(
                GuardrailEvent(
                    guardrail="rate_limit", failure_type="security", action="block", reason="agent_turns_per_minute"
                )
            )
        return decision


def configured_limit() -> int:
    raw = os.getenv("AGENT_RATE_LIMIT_PER_MINUTE", "").strip()
    if not raw:
        return DEFAULT_LIMIT
    try:
        limit = int(raw)
    except ValueError as error:
        raise RuntimeError("AGENT_RATE_LIMIT_PER_MINUTE debe ser un entero") from error
    if limit <= 0:
        raise RuntimeError("AGENT_RATE_LIMIT_PER_MINUTE debe ser mayor que cero")
    return limit


_limiter: AgentRateLimiter | None = None


def get_rate_limiter() -> AgentRateLimiter:
    """El limitador del proceso, sobre `REDIS_URL` (la conexión se abre con la primera operación)."""
    global _limiter
    if _limiter is None:
        client = redis.Redis.from_url(
            os.getenv("REDIS_URL") or DEFAULT_REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        _limiter = AgentRateLimiter(client)
    return _limiter


def use_rate_limiter(limiter: AgentRateLimiter | None) -> None:
    """Sustituye el limitador del proceso (tests)."""
    global _limiter
    _limiter = limiter
