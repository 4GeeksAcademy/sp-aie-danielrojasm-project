"""Pub/sub en memoria entre quien produce los eventos del chat y las conexiones WebSocket que los consumen.

Un canal por sesión (`chat.<session_id>`). El productor (`hub.LiveSession`, que ejecuta el agente) publica sin saber
cuántas conexiones hay; cada conexión se suscribe con su propia cola y la vacía a su ritmo. Así un supervisor que
observa la sesión recibe los mismos eventos que el cliente sin una segunda llamada al agente.

Vive en el bucle de eventos de la API: solo sirve con un proceso. Con varios, el canal pasaría a Redis Pub/Sub o a un
Stream sin cambiar la interfaz.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


def channel_for(session_id: str) -> str:
    return f"chat.{session_id}"


class ChatBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, channel: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[channel].add(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subscribers = self._subscribers.get(channel)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            del self._subscribers[channel]

    def publish(self, channel: str, event: dict[str, Any]) -> int:
        """Entrega el evento a cada suscriptor del canal; devuelve cuántos había."""
        subscribers = self._subscribers.get(channel, set())
        for queue in subscribers:
            queue.put_nowait(event)
        return len(subscribers)

    def subscribers(self, channel: str) -> int:
        return len(self._subscribers.get(channel, ()))
