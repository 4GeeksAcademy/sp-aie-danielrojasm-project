"""Contrato del chat por WebSocket con el First-line CX agent (BRIEFING de la Parte 2).

`ChatSession` es la entidad del BRIEFING §3; su `session_id` es también el `conversation_id` del agente (no hay otro
id para la misma conversación). Cada frame, en las dos direcciones, es `{"event": <nombre>, "data": {...}}`.

Cliente → servidor: `auth` (solo si el token no viajó en `?token=`), `user_message` e `interrupt_requested`.
Servidor → cliente: `session_snapshot` (al conectar y al reconectar), `user_message` (eco del turno, para todos los
suscriptores), `token_chunk`, `generation_interrupted`, `generation_completed`, `generation_failed` y `chat_error`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from services.api.knowledge_models import MAX_QUESTION_LENGTH


AGENT_ID = "first_line_cx"
SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"

SessionStatus = Literal["active", "interrupted", "closed"]
MessageRole = Literal["user", "assistant"]
# `streaming` solo existe mientras el agente genera; al terminar pasa a `completed`, `interrupted` o `failed`.
MessageStatus = Literal["streaming", "completed", "interrupted", "failed"]


class ChatSession(BaseModel):
    session_id: str
    agent_id: Literal["first_line_cx"] = AGENT_ID
    user_id: str = Field(description="Usuario autenticado que chatea con el agente.")
    client_id: str | None = Field(default=None, description="Marca cliente (B2B) a la que pertenece la conversación.")
    status: SessionStatus = "active"
    created_at: datetime


class ChatMessage(BaseModel):
    message_id: str
    session_id: str
    role: MessageRole
    text: str
    status: MessageStatus
    created_at: datetime


class ChatSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str | None = Field(default=None, max_length=64)


class ChatSessionRead(ChatSession):
    messages: list[ChatMessage]


# --- Frames del cliente ------------------------------------------------------------------------------------------


ChatText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_LENGTH)]


class AuthData(BaseModel):
    token: str


class UserMessageData(BaseModel):
    session_id: str
    text: ChatText


class InterruptRequestedData(BaseModel):
    session_id: str
    new_input: ChatText


class AuthFrame(BaseModel):
    event: Literal["auth"]
    data: AuthData


class UserMessageFrame(BaseModel):
    event: Literal["user_message"]
    data: UserMessageData


class InterruptRequestedFrame(BaseModel):
    event: Literal["interrupt_requested"]
    data: InterruptRequestedData


ClientFrame = Annotated[UserMessageFrame | InterruptRequestedFrame, Field(discriminator="event")]
client_frame = TypeAdapter(ClientFrame)


# --- Eventos del servidor ----------------------------------------------------------------------------------------


def event(name: str, **data: Any) -> dict[str, Any]:
    """Un evento nombrado del servidor, listo para `send_json`."""
    return {"event": name, "data": data}


def token_chunk(session_id: str, message_id: str, token: str, sequence: int) -> dict[str, Any]:
    return event("token_chunk", session_id=session_id, message_id=message_id, token=token, sequence=sequence)


def generation_interrupted(session_id: str, message: ChatMessage, new_input: str) -> dict[str, Any]:
    return event(
        "generation_interrupted",
        session_id=session_id,
        message_id=message.message_id,
        status="interrupted",
        text=message.text,
        new_input=new_input,
    )


def generation_completed(session_id: str, message: ChatMessage) -> dict[str, Any]:
    # `text` es la respuesta final tras el guard de salida: es la que queda en el historial.
    return event("generation_completed", session_id=session_id, message_id=message.message_id, text=message.text)


def generation_failed(session_id: str, message: ChatMessage, detail: str) -> dict[str, Any]:
    return event("generation_failed", session_id=session_id, message_id=message.message_id, detail=detail)


def user_message(session_id: str, message: ChatMessage) -> dict[str, Any]:
    return event("user_message", session_id=session_id, message_id=message.message_id, text=message.text)


def chat_error(session_id: str, detail: str) -> dict[str, Any]:
    return event("chat_error", session_id=session_id, detail=detail)
