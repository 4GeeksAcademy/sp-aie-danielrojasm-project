"""Chat por WebSocket con el First-line CX agent: autenticación, contrato de eventos, abort y rehidratación.

El grafo es el real (reglas de enrutado, RAG falso). El modelo es un stream falso que entrega el JSON de la respuesta
en trozos de 4 caracteres con una pausa entre ellos, y registra cuántos trozos se consumieron y si se cerró la
conexión: así se mide que una interrupción corta la generación y no solo deja de mostrarla.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from data.pipelines import rag
from services.api.auth_models import UserRole
from services.api.main import app
from services.support_agent import nodes
from services.support_agent.chat.store import get_chat_store
from services.support_agent.memory import self_evaluation
from services.support_agent.routing import route_by_rules
from tests.helpers import DEFAULT_PASSWORD


QUESTION = "¿Cuál es la ventana de devolución estándar?"
TRACKING_ANSWER = "Para rastrear tu pedido, revisa el enlace de seguimiento que recibiste por correo. " * 6
RETURN_INPUT = "espera, quiero hacer una devolución, no rastrear el pedido"
RETURN_ANSWER = "Claro: puedes devolverlo en 30 días naturales desde la entrega.\nFuente: Ventana"
CHUNK = {"source_document": "returns-policy", "section": "Ventana", "chunk_index": 1, "text": "30 días naturales."}


class FakeStream:
    def __init__(self, answer: str, delay: float):
        body = json.dumps({"respuesta": answer, "propuesta_memoria": None})
        self.parts = [body[index : index + 4] for index in range(0, len(body), 4)]
        self.delay = delay
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for part in self.parts:
            if self.closed:
                return
            time.sleep(self.delay)
            self.consumed += 1
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=part))])

    def close(self) -> None:
        self.closed = True


class FakeLLM:
    """Responde la devolución rápido y el resto despacio; cada llamada deja su stream en `streams`."""

    def __init__(self, slow_delay: float = 0.003):
        self.slow_delay = slow_delay
        self.streams: list[FakeStream] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request: Any) -> FakeStream:
        assert request.get("stream") is True
        prompt = json.dumps(request["messages"], ensure_ascii=False)
        stream = FakeStream(RETURN_ANSWER, 0) if RETURN_INPUT in prompt else FakeStream(TRACKING_ANSWER, self.slow_delay)
        self.streams.append(stream)
        return stream


@pytest.fixture
def llm(monkeypatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(nodes, "plan_route", route_by_rules)
    monkeypatch.setattr(rag, "retrieve", lambda question: [CHUNK])
    monkeypatch.setattr(self_evaluation, "load_settings", lambda: SimpleNamespace(generation_model="fake-model"))
    monkeypatch.setattr(self_evaluation, "get_llm_client", lambda: fake)
    return fake


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str, role: UserRole | None = None, make_user=None) -> tuple[str, str]:
    user = make_user(email=email, role=role)
    token = client.post("/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}).json()["access_token"]
    return user.id, token


@pytest.fixture
def owner(client, make_user) -> tuple[str, str]:
    return login(client, "cliente@example.com", make_user=make_user)


@pytest.fixture
def session_id(client, owner) -> str:
    response = client.post(
        "/agent/chat/sessions", json={"client_id": "luna-cosmetics"}, headers={"Authorization": f"Bearer {owner[1]}"}
    )
    assert response.status_code == 201
    return response.json()["session_id"]


def socket_url(session_id: str, token: str | None = None) -> str:
    url = f"/agent/chat/sessions/{session_id}/ws"
    return f"{url}?token={token}" if token else url


def until(ws, name: str, collected: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Lee eventos hasta el primero llamado `name` (los anteriores quedan en `collected`)."""
    while True:
        event = ws.receive_json()
        if event["event"] == name:
            return event
        if collected is not None:
            collected.append(event)


def send(ws, name: str, session_id: str, **data: Any) -> None:
    ws.send_json({"event": name, "data": {"session_id": session_id, **data}})


# --- Sesión y autenticación ------------------------------------------------------------------------------------


def test_creates_a_chat_session_with_the_briefing_fields(client, owner, session_id):
    response = client.get(f"/agent/chat/sessions/{session_id}", headers={"Authorization": f"Bearer {owner[1]}"})

    body = response.json()
    assert response.status_code == 200
    assert {key: body[key] for key in ("session_id", "agent_id", "user_id", "client_id", "status")} == {
        "session_id": session_id,
        "agent_id": "first_line_cx",
        "user_id": owner[0],
        "client_id": "luna-cosmetics",
        "status": "active",
    }
    assert body["created_at"] and body["messages"] == []


def test_session_endpoints_require_the_backoffice_jwt(client):
    assert client.post("/agent/chat/sessions", json={}).status_code == 401


def test_closes_the_socket_with_an_invalid_token_before_any_chat_event(client, session_id):
    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect(socket_url(session_id, "no-es-un-jwt")) as ws:
            ws.receive_json()

    assert rejected.value.code == 1008


def test_closes_the_socket_when_the_first_frame_is_not_auth(client, session_id):
    with client.websocket_connect(socket_url(session_id)) as ws:
        send(ws, "user_message", session_id, text=QUESTION)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()

    assert closed.value.code == 1008


def test_accepts_the_token_in_a_first_auth_frame(client, owner, session_id):
    with client.websocket_connect(socket_url(session_id)) as ws:
        ws.send_json({"event": "auth", "data": {"token": owner[1]}})
        snapshot = ws.receive_json()

    assert snapshot == {
        "event": "session_snapshot",
        "data": {"session_id": session_id, "status": "active", "messages": [], "generation": None},
    }


def test_requires_an_existing_session(client, owner):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(socket_url("chat_no_existe", owner[1])) as ws:
            ws.receive_json()

    assert closed.value.code == 4404


def test_another_customer_cannot_open_the_session(client, session_id, make_user):
    _, intruder = login(client, "otra@example.com", make_user=make_user)

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(socket_url(session_id, intruder)) as ws:
            ws.receive_json()

    assert closed.value.code == 4403


# --- Contrato de eventos y streaming ---------------------------------------------------------------------------


def test_streams_the_answer_token_by_token_and_completes(client, llm, owner, session_id):
    with client.websocket_connect(socket_url(session_id, owner[1])) as ws:
        assert ws.receive_json()["event"] == "session_snapshot"
        send(ws, "user_message", session_id, text=QUESTION)
        echo = ws.receive_json()
        chunks: list[dict[str, Any]] = []
        completed = until(ws, "generation_completed", chunks)

    assert echo["event"] == "user_message"
    assert set(echo["data"]) == {"session_id", "message_id", "text"} and echo["data"]["text"] == QUESTION
    assert {chunk["event"] for chunk in chunks} == {"token_chunk"}
    assert len(chunks) > 10, "la respuesta tiene que llegar en muchos trozos, no de una vez"
    first = chunks[0]["data"]
    assert set(first) == {"session_id", "message_id", "token", "sequence"} and first["session_id"] == session_id
    assert [chunk["data"]["sequence"] for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert {chunk["data"]["message_id"] for chunk in chunks} == {completed["data"]["message_id"]}
    assert "".join(chunk["data"]["token"] for chunk in chunks) == TRACKING_ANSWER
    assert set(completed["data"]) == {"session_id", "message_id", "text"}
    assert completed["data"]["text"].startswith(TRACKING_ANSWER.strip())
    history = get_chat_store().messages(session_id)
    assert [(message.role, message.status) for message in history] == [("user", "completed"), ("assistant", "completed")]


def test_rejects_invalid_frames_and_messages_while_the_agent_is_answering(client, llm, owner, session_id):
    with client.websocket_connect(socket_url(session_id, owner[1])) as ws:
        ws.receive_json()
        ws.send_text("no es json")
        invalid = ws.receive_json()
        send(ws, "user_message", "chat_otra_sesion", text=QUESTION)
        wrong_session = ws.receive_json()
        send(ws, "user_message", session_id, text=QUESTION)
        until(ws, "token_chunk")
        send(ws, "user_message", session_id, text="otra pregunta")
        busy = until(ws, "chat_error")
        until(ws, "generation_completed")

    assert invalid["event"] == "chat_error" and "user_message" in invalid["data"]["detail"]
    assert wrong_session["event"] == "chat_error" and "session_id" in wrong_session["data"]["detail"]
    assert "interrupt_requested" in busy["data"]["detail"]
    assert len(llm.streams) == 1


def test_interrupt_aborts_the_generation_and_starts_a_new_turn(client, llm, owner, session_id):
    with client.websocket_connect(socket_url(session_id, owner[1])) as ws:
        ws.receive_json()
        send(ws, "user_message", session_id, text=QUESTION)
        until(ws, "user_message")
        shown = [until(ws, "token_chunk") for _ in range(5)]
        send(ws, "interrupt_requested", session_id, new_input=RETURN_INPUT)
        before: list[dict[str, Any]] = []
        interrupted = until(ws, "generation_interrupted", before)
        after: list[dict[str, Any]] = []
        completed = until(ws, "generation_completed", after)

    original = shown[0]["data"]["message_id"]
    shown += [event for event in before if event["event"] == "token_chunk"]
    partial = "".join(event["data"]["token"] for event in shown)
    assert interrupted["data"] == {
        "session_id": session_id,
        "message_id": original,
        "status": "interrupted",
        "text": partial,
        "new_input": RETURN_INPUT,
    }
    # Ni un token más de la generación original, y el stream del modelo se cerró a mitad.
    assert not [event for event in after if event["event"] == "token_chunk" and event["data"]["message_id"] == original]
    slow = llm.streams[0]
    assert slow.closed and slow.consumed < len(slow.parts)
    # El turno nuevo es otro mensaje que responde a `new_input`.
    echo = next(event for event in after if event["event"] == "user_message")
    assert echo["data"]["text"] == RETURN_INPUT
    assert completed["data"]["message_id"] != original
    assert "devolverlo en 30 días" in completed["data"]["text"]
    new_tokens = [event["data"] for event in after if event["event"] == "token_chunk"]
    assert new_tokens and new_tokens[0]["sequence"] == 1
    history = [(message.role, message.status, message.text) for message in get_chat_store().messages(session_id)]
    assert history[1] == ("assistant", "interrupted", partial)
    assert [(role, status) for role, status, _ in history] == [
        ("user", "completed"),
        ("assistant", "interrupted"),
        ("user", "completed"),
        ("assistant", "completed"),
    ]


def test_interrupt_without_a_generation_is_a_new_turn(client, llm, owner, session_id):
    with client.websocket_connect(socket_url(session_id, owner[1])) as ws:
        ws.receive_json()
        send(ws, "interrupt_requested", session_id, new_input=RETURN_INPUT)
        events: list[dict[str, Any]] = []
        until(ws, "generation_completed", events)

    assert "generation_interrupted" not in {event["event"] for event in events}
    assert [message.status for message in get_chat_store().messages(session_id)] == ["completed", "completed"]


# --- Reconexión y pub/sub --------------------------------------------------------------------------------------


def test_reconnecting_with_the_same_session_restores_the_thread(client, llm, owner, session_id):
    with client.websocket_connect(socket_url(session_id, owner[1])) as ws:
        ws.receive_json()
        send(ws, "user_message", session_id, text=QUESTION)
        completed = until(ws, "generation_completed")

    with client.websocket_connect(socket_url(session_id, owner[1])) as ws:
        snapshot = ws.receive_json()

    messages = snapshot["data"]["messages"]
    assert snapshot["event"] == "session_snapshot" and snapshot["data"]["generation"] is None
    assert [(message["role"], message["status"]) for message in messages] == [
        ("user", "completed"),
        ("assistant", "completed"),
    ]
    assert messages[0]["text"] == QUESTION
    assert messages[1]["message_id"] == completed["data"]["message_id"]
    assert messages[1]["text"] == completed["data"]["text"]


def test_reconnecting_mid_answer_resumes_from_the_partial_text(client, llm, owner, session_id):
    with client.websocket_connect(socket_url(session_id, owner[1])) as first:
        first.receive_json()
        send(first, "user_message", session_id, text=QUESTION)
        until(first, "user_message")
        until(first, "token_chunk")
        with client.websocket_connect(socket_url(session_id, owner[1])) as second:
            snapshot = second.receive_json()["data"]
            rest: list[dict[str, Any]] = []
            completed = until(second, "generation_completed", rest)

    streaming = snapshot["messages"][-1]
    assert streaming["status"] == "streaming"
    assert snapshot["generation"] == {"message_id": streaming["message_id"], "sequence": snapshot["generation"]["sequence"]}
    tokens = [event["data"] for event in rest if event["event"] == "token_chunk"]
    assert tokens[0]["sequence"] == snapshot["generation"]["sequence"] + 1
    assert streaming["text"] + "".join(token["token"] for token in tokens) == TRACKING_ANSWER
    assert completed["data"]["message_id"] == streaming["message_id"]


def test_every_subscriber_gets_the_same_events_from_a_single_agent_call(client, llm, owner, session_id, make_user):
    _, supervisor = login(client, "valentina@example.com", role=UserRole.MANAGER, make_user=make_user)
    seen: dict[str, list[dict[str, Any]]] = {}

    with client.websocket_connect(socket_url(session_id, owner[1])) as customer:
        customer.receive_json()
        with client.websocket_connect(socket_url(session_id, supervisor)) as observer:
            observer.receive_json()
            send(observer, "user_message", session_id, text="el supervisor no escribe")
            read_only = observer.receive_json()
            send(customer, "user_message", session_id, text=QUESTION)
            for name, ws in (("customer", customer), ("supervisor", observer)):
                seen[name] = []
                until(ws, "generation_completed", seen[name])

    assert read_only["event"] == "chat_error" and "observando" in read_only["data"]["detail"]
    assert seen["customer"] == seen["supervisor"]
    assert len(llm.streams) == 1


def test_a_closed_socket_does_not_stop_the_turn(client, llm, owner, session_id):
    with client.websocket_connect(socket_url(session_id, owner[1])) as ws:
        ws.receive_json()
        send(ws, "user_message", session_id, text=QUESTION)
        until(ws, "token_chunk")

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        statuses = [message.status for message in get_chat_store().messages(session_id)]
        if statuses == ["completed", "completed"]:
            break
        threading.Event().wait(0.05)
    assert statuses == ["completed", "completed"]
