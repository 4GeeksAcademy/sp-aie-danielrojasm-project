"""Chat por WebSocket con el First-line CX agent: amplía `/agent` (el de `POST /agent/query`) sin tocar el grafo.

- `POST /agent/chat/sessions`: abre una `ChatSession` del usuario autenticado.
- `GET /agent/chat/sessions/{session_id}`: la sesión con su historial.
- `WS /agent/chat/sessions/{session_id}/ws`: canal bidireccional ligado a esa sesión.

El socket usa el mismo JWT que la API del backoffice: en `?token=` o, si no viene, en un primer frame
`{"event": "auth", "data": {"token": "…"}}` antes de 5 s. Sin autenticación válida se cierra antes de enviar ningún
evento de chat. Códigos de cierre: 1008 sin autenticación, 4404 sesión inexistente, 4403 sesión ajena,
1011 historial no disponible.

Cada conexión se suscribe al canal de su sesión (`hub.ChatHub.join`) y recibe primero un `session_snapshot`; un
supervisor (rol `admin` o `manager`) puede observar sesiones ajenas, pero solo su dueño envía mensajes.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from services.api.auth_models import User, UserRole
from services.api.security import get_current_user, user_from_token
from services.support_agent.chat import models
from services.support_agent.chat.hub import LiveSession, get_chat_hub, utc_now
from services.support_agent.chat.models import (
    SESSION_ID_PATTERN,
    AuthFrame,
    ChatSession,
    ChatSessionCreate,
    ChatSessionRead,
    InterruptRequestedFrame,
    client_frame,
)
from services.support_agent.chat.store import ChatStoreUnavailableError, get_chat_store


logger = logging.getLogger("trackflow.chat")

router = APIRouter(prefix="/agent/chat", tags=["agent"])

AUTH_FRAME_TIMEOUT_SECONDS = 5
CLOSE_UNAUTHENTICATED = status.WS_1008_POLICY_VIOLATION
CLOSE_UNAVAILABLE = status.WS_1011_INTERNAL_ERROR
CLOSE_NOT_FOUND = 4404
CLOSE_FORBIDDEN = 4403
SUPERVISOR_ROLES = {UserRole.ADMIN.value, UserRole.MANAGER.value}

STORE_UNAVAILABLE_DETAIL = "El historial del chat no está disponible ahora mismo. Inténtalo de nuevo en unos minutos."
SESSION_NOT_FOUND_DETAIL = "No existe esa conversación o no tienes acceso a ella."
READ_ONLY_DETAIL = "Estás observando esta conversación: solo su titular puede escribir al agente."
INVALID_FRAME_DETAIL = (
    "Mensaje no válido: envía user_message con text, o interrupt_requested con new_input (1 a 1000 caracteres)."
)
WRONG_SESSION_DETAIL = "El session_id del mensaje no es el de esta conexión."


def can_view(session: ChatSession, user: User) -> bool:
    return session.user_id == user.id or user.role in SUPERVISOR_ROLES


def _load_session(session_id: str) -> ChatSession | None:
    if not re.fullmatch(SESSION_ID_PATTERN, session_id):
        return None
    return get_chat_store().get_session(session_id)


@router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=ChatSession)
def create_session(body: ChatSessionCreate, user: User = Depends(get_current_user)) -> ChatSession:
    session = ChatSession(
        session_id=f"chat_{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        client_id=body.client_id,
        created_at=utc_now(),
    )
    try:
        get_chat_store().create_session(session)
    except ChatStoreUnavailableError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, STORE_UNAVAILABLE_DETAIL) from error
    logger.info("chat_session_created session_id=%s user_id=%s", session.session_id, user.id)
    return session


@router.get("/sessions/{session_id}", response_model=ChatSessionRead)
def read_session(session_id: str, user: User = Depends(get_current_user)) -> ChatSessionRead:
    try:
        session = _load_session(session_id)
        if session is None or not can_view(session, user):
            raise HTTPException(status.HTTP_404_NOT_FOUND, SESSION_NOT_FOUND_DETAIL)
        messages = get_chat_store().messages(session_id)
    except ChatStoreUnavailableError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, STORE_UNAVAILABLE_DETAIL) from error
    return ChatSessionRead(**session.model_dump(), messages=messages)


@router.websocket("/sessions/{session_id}/ws")
async def chat_socket(websocket: WebSocket, session_id: str, token: str | None = None) -> None:
    # Se acepta antes de validar para cerrar con 1008: un handshake rechazado le llega al navegador como 1006, sin
    # motivo, y el cliente no sabría que tiene que volver al login en lugar de reintentar.
    await websocket.accept()
    if token is not None:
        user = await asyncio.to_thread(user_from_token, token)
    else:
        user = await _authenticate_first_frame(websocket)
    if user is None:
        await websocket.close(code=CLOSE_UNAUTHENTICATED, reason="Falta un token válido o ha caducado.")
        logger.warning("chat_rejected session_id=%s reason=unauthenticated", session_id)
        return

    try:
        session = await asyncio.to_thread(_load_session, session_id)
    except ChatStoreUnavailableError:
        await websocket.close(code=CLOSE_UNAVAILABLE, reason=STORE_UNAVAILABLE_DETAIL)
        logger.error("chat_rejected session_id=%s reason=store_unavailable", session_id)
        return
    if session is None:
        await websocket.close(code=CLOSE_NOT_FOUND, reason=SESSION_NOT_FOUND_DETAIL)
        return
    if not can_view(session, user):
        await websocket.close(code=CLOSE_FORBIDDEN, reason=SESSION_NOT_FOUND_DETAIL)
        logger.warning("chat_rejected session_id=%s user_id=%s reason=forbidden", session_id, user.id)
        return

    hub = get_chat_hub()
    try:
        live, queue = await hub.join(session)
    except ChatStoreUnavailableError:
        await websocket.close(code=CLOSE_UNAVAILABLE, reason=STORE_UNAVAILABLE_DETAIL)
        return
    owner = session.user_id == user.id
    logger.info(
        "chat_connected session_id=%s user_id=%s owner=%s subscribers=%d",
        session_id,
        user.id,
        owner,
        hub.broker.subscribers(live.channel),
    )
    # Solo esta tarea escribe en el socket: los eventos del canal y los errores de esta conexión pasan por su cola.
    sender = asyncio.create_task(_forward(websocket, queue))
    try:
        while True:
            raw = await websocket.receive_text()
            reply = await _handle_frame(raw, live, session_id, owner)
            if reply is not None:
                queue.put_nowait(models.chat_error(session_id, reply))
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        hub.leave(live, queue)
        logger.info("chat_disconnected session_id=%s user_id=%s", session_id, user.id)


async def _handle_frame(raw: str, live: LiveSession, session_id: str, owner: bool) -> str | None:
    """Aplica un frame del cliente. Devuelve el motivo si no se aceptó."""
    try:
        frame = client_frame.validate_json(raw)
    except ValidationError:
        return INVALID_FRAME_DETAIL
    if frame.data.session_id != session_id:
        return WRONG_SESSION_DETAIL
    if not owner:
        return READ_ONLY_DETAIL
    if isinstance(frame, InterruptRequestedFrame):
        await live.interrupt(frame.data.new_input)
        return None
    return await live.send(frame.data.text)


async def _authenticate_first_frame(websocket: WebSocket) -> User | None:
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), AUTH_FRAME_TIMEOUT_SECONDS)
        frame = AuthFrame.model_validate_json(raw)
    except (TimeoutError, ValidationError, WebSocketDisconnect):
        return None
    return await asyncio.to_thread(user_from_token, frame.data.token)


async def _forward(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    try:
        while True:
            await websocket.send_json(await queue.get())
    except (WebSocketDisconnect, RuntimeError):
        # La conexión se cerró mientras se enviaba: el bucle de recepción lo detecta y limpia.
        return
