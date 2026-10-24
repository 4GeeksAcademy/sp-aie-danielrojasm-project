"""Historial de las sesiones de chat en Redis (el mismo `REDIS_URL` que Celery y la memoria del agente, con AOF).

- `trackflow:chat:sessions`: hash `session_id` → `ChatSession` en JSON.
- `trackflow:chat:messages:<session_id>`: hash `message_id` → `ChatMessage` en JSON.
- `trackflow:chat:order:<session_id>`: lista de `message_id` en orden de llegada.

Es lo que rehidrata la conversación al reconectar: el agente no guarda historial y su checkpoint se libera al terminar
cada turno. Un mensaje interrumpido se reescribe con su estado final, nunca se borra. Cualquier fallo de Redis es
`ChatStoreUnavailableError`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import redis

from services.support_agent.chat.models import ChatMessage, ChatSession, SessionStatus


NAMESPACE = "trackflow:chat"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"


class ChatStoreUnavailableError(RuntimeError):
    """Redis no responde: no se puede leer ni guardar el historial del chat."""


class ChatStore:
    def __init__(self, client: redis.Redis, namespace: str = NAMESPACE):
        self.client = client
        self.namespace = namespace
        self.sessions_key = f"{namespace}:sessions"

    def create_session(self, session: ChatSession) -> None:
        with self._guard():
            self.client.hset(self.sessions_key, session.session_id, session.model_dump_json())

    def get_session(self, session_id: str) -> ChatSession | None:
        with self._guard():
            raw = self.client.hget(self.sessions_key, session_id)
        return ChatSession.model_validate_json(raw) if raw else None

    def set_status(self, session_id: str, status: SessionStatus) -> ChatSession | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        updated = session.model_copy(update={"status": status})
        self.create_session(updated)
        return updated

    def save_message(self, message: ChatMessage) -> None:
        """Añade el mensaje al final del hilo o, si ya existe, guarda su nuevo estado en el mismo sitio."""
        with self._guard():
            added = self.client.hset(self._messages_key(message.session_id), message.message_id, message.model_dump_json())
            if added:
                self.client.rpush(self._order_key(message.session_id), message.message_id)

    def messages(self, session_id: str) -> list[ChatMessage]:
        with self._guard():
            order = self.client.lrange(self._order_key(session_id), 0, -1)
            raw = self.client.hgetall(self._messages_key(session_id))
        return [ChatMessage.model_validate_json(raw[message_id]) for message_id in order if message_id in raw]

    def _messages_key(self, session_id: str) -> str:
        return f"{self.namespace}:messages:{session_id}"

    def _order_key(self, session_id: str) -> str:
        return f"{self.namespace}:order:{session_id}"

    @contextmanager
    def _guard(self) -> Iterator[None]:
        try:
            yield
        except redis.RedisError as error:
            raise ChatStoreUnavailableError("El historial del chat no está disponible ahora mismo.") from error


_store: ChatStore | None = None


def get_chat_store() -> ChatStore:
    """El almacén del proceso, sobre `REDIS_URL` (la conexión se abre con la primera operación)."""
    global _store
    if _store is None:
        client = redis.Redis.from_url(
            os.getenv("REDIS_URL") or DEFAULT_REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        _store = ChatStore(client)
    return _store


def use_chat_store(store: ChatStore | None) -> None:
    """Sustituye el almacén del proceso (tests)."""
    global _store
    _store = store
