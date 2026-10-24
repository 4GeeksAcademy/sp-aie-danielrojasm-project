"""Productor de los eventos del chat: una `LiveSession` por sesión con conexiones abiertas o un turno en curso.

La `LiveSession` es la única que llama al agente. Las conexiones WebSocket solo le pasan los mensajes del usuario y
consumen sus eventos desde el broker (`broker.py`), así que N conexiones a la misma sesión son una sola generación.

Un turno: se guarda y publica el `user_message`, se abre un mensaje del asistente en `streaming` y `run_agent` corre
en un hilo con `on_token` (cada token vuelve al bucle de eventos con `call_soon_threadsafe` y sale como
`token_chunk`) y un `abort` propio. Al terminar, el mensaje queda `completed` con la respuesta final del grafo (tras
el guard de salida) o `failed`.

Interrupción (`interrupt_requested`): se pone el `abort` del turno (el runner deja de emitir y el stream del modelo
se cierra), el turno deja de aceptar tokens en ese mismo instante, el mensaje parcial queda `interrupted` con el
texto ya mostrado y se publica `generation_interrupted`. Después empieza un turno nuevo con `new_input`; el mensaje
interrumpido no se borra ni se reescribe con la respuesta nueva.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.support_agent.chat import models
from services.support_agent.chat.broker import ChatBroker, channel_for
from services.support_agent.chat.models import ChatMessage, ChatSession, SessionStatus
from services.support_agent.chat.store import ChatStoreUnavailableError, get_chat_store
from services.support_agent.runner import AgentRunError, run_agent
from services.support_agent.streaming import GenerationAborted


logger = logging.getLogger("trackflow.chat")

AGENT_FAILED_DETAIL = (
    "El agente de soporte no pudo responder a este mensaje. Inténtalo de nuevo y, si sigue fallando, avisa al "
    "equipo técnico con la referencia {run_id}."
)
AGENT_UNEXPECTED_DETAIL = "El agente de soporte no pudo responder a este mensaje. Inténtalo de nuevo en unos minutos."
BUSY_DETAIL = "El agente todavía está respondiendo: envía interrupt_requested para redirigirlo."
HISTORY_NOT_SAVED_DETAIL = (
    "El mensaje se mostró, pero no se pudo guardar en el historial: si recargas la conversación, puede faltar."
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


@dataclass
class Generation:
    message: ChatMessage
    abort: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task[None] | None = None
    sequence: int = 0
    parts: list[str] = field(default_factory=list)
    # Interrumpida: desde este instante ningún token suyo llega a los suscriptores.
    stopped: bool = False

    @property
    def text(self) -> str:
        return "".join(self.parts)


class LiveSession:
    def __init__(self, session: ChatSession, history: list[ChatMessage], hub: ChatHub):
        self.session = session
        self.messages = history
        self.hub = hub
        self.channel = channel_for(session.session_id)
        self.generation: Generation | None = None
        self.lock = asyncio.Lock()

    @property
    def session_id(self) -> str:
        return self.session.session_id

    def snapshot(self) -> dict[str, Any]:
        """Estado completo del hilo, con el texto ya emitido del mensaje en curso y su último `sequence`."""
        generation = self.generation
        messages = []
        for message in self.messages:
            if generation is not None and message.message_id == generation.message.message_id:
                message = message.model_copy(update={"text": generation.text})
            messages.append(message.model_dump(mode="json"))
        return models.event(
            "session_snapshot",
            session_id=self.session_id,
            status=self.session.status,
            messages=messages,
            generation={"message_id": generation.message.message_id, "sequence": generation.sequence}
            if generation
            else None,
        )

    async def send(self, text: str) -> str | None:
        """Turno nuevo del usuario. Devuelve el motivo si no se acepta (hay una generación en curso)."""
        async with self.lock:
            if self.generation is not None:
                return BUSY_DETAIL
            await self._start_turn(text)
            return None

    async def interrupt(self, new_input: str) -> None:
        """Aborta la generación en curso (si la hay) y arranca un turno nuevo con `new_input`."""
        async with self.lock:
            generation = self.generation
            if generation is not None:
                generation.abort.set()
                generation.stopped = True
                self.generation = None
                interrupted = self._replace(generation.message, text=generation.text, status="interrupted")
                logger.info(
                    "chat_generation_interrupted session_id=%s message_id=%s tokens=%d",
                    self.session_id,
                    interrupted.message_id,
                    generation.sequence,
                )
                await self._set_status("interrupted")
                self._publish(models.generation_interrupted(self.session_id, interrupted, new_input))
                await self._persist(interrupted)
                if generation.task is not None:
                    await generation.task
            await self._start_turn(new_input)

    async def _start_turn(self, text: str) -> None:
        if self.session.status != "active":
            await self._set_status("active")
        user = ChatMessage(
            message_id=new_message_id(),
            session_id=self.session_id,
            role="user",
            text=text,
            status="completed",
            created_at=utc_now(),
        )
        self.messages.append(user)
        self._publish(models.user_message(self.session_id, user))
        await self._persist(user)
        reply = ChatMessage(
            message_id=new_message_id(),
            session_id=self.session_id,
            role="assistant",
            text="",
            status="streaming",
            created_at=utc_now(),
        )
        self.messages.append(reply)
        generation = Generation(message=reply)
        self.generation = generation
        generation.task = asyncio.create_task(self._generate(generation, text))

    async def _generate(self, generation: Generation, text: str) -> None:
        loop = asyncio.get_running_loop()

        def on_token(token: str) -> None:
            loop.call_soon_threadsafe(self._on_token, generation, token)

        logger.info("chat_generation_started session_id=%s message_id=%s", self.session_id, generation.message.message_id)
        try:
            run = await asyncio.to_thread(
                run_agent,
                text,
                conversation_id=self.session_id,
                user_id=self.session.user_id,
                on_token=on_token,
                abort=generation.abort,
            )
        except GenerationAborted:
            return
        except AgentRunError as error:
            await self._fail(generation, AGENT_FAILED_DETAIL.format(run_id=error.run_id))
            return
        except Exception:
            logger.exception("chat_generation_failed session_id=%s", self.session_id)
            await self._fail(generation, AGENT_UNEXPECTED_DETAIL)
            return
        if generation.stopped:
            return
        if "error" in run.state:
            await self._fail(generation, run.state["error"])
            return
        self.generation = None
        completed = self._replace(generation.message, text=run.state["answer"], status="completed")
        logger.info(
            "chat_generation_completed session_id=%s message_id=%s run_id=%s tokens=%d",
            self.session_id,
            completed.message_id,
            run.run_id,
            generation.sequence,
        )
        self._publish(models.generation_completed(self.session_id, completed))
        await self._persist(completed)
        self.hub.release_if_idle(self)

    def _on_token(self, generation: Generation, token: str) -> None:
        if generation.stopped or self.generation is not generation:
            return
        generation.sequence += 1
        generation.parts.append(token)
        self._publish(models.token_chunk(self.session_id, generation.message.message_id, token, generation.sequence))

    async def _fail(self, generation: Generation, detail: str) -> None:
        if generation.stopped:
            return
        self.generation = None
        failed = self._replace(generation.message, text=generation.text, status="failed")
        self._publish(models.generation_failed(self.session_id, failed, detail))
        await self._persist(failed)
        self.hub.release_if_idle(self)

    def _replace(self, message: ChatMessage, **changes: Any) -> ChatMessage:
        updated = message.model_copy(update=changes)
        self.messages = [updated if item.message_id == message.message_id else item for item in self.messages]
        return updated

    def _publish(self, event: dict[str, Any]) -> None:
        self.hub.broker.publish(self.channel, event)

    async def _persist(self, message: ChatMessage) -> None:
        try:
            await asyncio.to_thread(get_chat_store().save_message, message)
        except ChatStoreUnavailableError:
            logger.error("chat_history_not_saved session_id=%s message_id=%s", self.session_id, message.message_id)
            self._publish(models.chat_error(self.session_id, HISTORY_NOT_SAVED_DETAIL))

    async def _set_status(self, status: SessionStatus) -> None:
        self.session = self.session.model_copy(update={"status": status})
        try:
            await asyncio.to_thread(get_chat_store().set_status, self.session_id, status)
        except ChatStoreUnavailableError:
            logger.error("chat_status_not_saved session_id=%s status=%s", self.session_id, status)


class ChatHub:
    """Sesiones vivas del proceso y el broker por el que salen sus eventos."""

    def __init__(self, broker: ChatBroker | None = None):
        self.broker = broker or ChatBroker()
        self.sessions: dict[str, LiveSession] = {}

    async def join(self, session: ChatSession) -> tuple[LiveSession, asyncio.Queue[dict[str, Any]]]:
        """Suscribe una conexión y le deja la `session_snapshot` como primer evento de su cola.

        Suscripción y snapshot ocurren sin ceder el bucle de eventos: ningún token cae entre los dos.
        """
        live = self.sessions.get(session.session_id)
        if live is None:
            history = await asyncio.to_thread(get_chat_store().messages, session.session_id)
            live = self.sessions.get(session.session_id)
            if live is None:
                live = LiveSession(session, history, self)
                self.sessions[session.session_id] = live
        queue = self.broker.subscribe(live.channel)
        queue.put_nowait(live.snapshot())
        return live, queue

    def leave(self, live: LiveSession, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.broker.unsubscribe(live.channel, queue)
        self.release_if_idle(live)

    def release_if_idle(self, live: LiveSession) -> None:
        """Sin conexiones ni generación, la sesión deja la memoria: su historial ya está en Redis."""
        if live.generation is None and not self.broker.subscribers(live.channel):
            if self.sessions.get(live.session_id) is live:
                del self.sessions[live.session_id]


_hub: ChatHub | None = None


def get_chat_hub() -> ChatHub:
    global _hub
    if _hub is None:
        _hub = ChatHub()
    return _hub


def use_chat_hub(hub: ChatHub | None) -> None:
    """Sustituye el hub del proceso (tests)."""
    global _hub
    _hub = hub
