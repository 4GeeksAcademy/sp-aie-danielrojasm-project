"""`GET /rfps/events`: notificación SSE `rfp_ticket_created` probada sobre el cable, con uvicorn real.

`TestClient` espera a que la respuesta termine y un stream SSE no termina nunca, así que los tests de streaming
levantan la API en un hilo y leen con `httpx.stream`. Redis es el `fakeredis` de `tests/conftest.py`: el test
publica como lo haría el worker y la API lee del mismo servidor en memoria.
"""

import json
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timezone

import fakeredis
import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from data.pipelines.rfp_intake import runner
from data.pipelines.rfp_intake.schema import RfpTicket
from services.api.main import app
from services.api.security import create_access_token
from services.rfp_intake import events
from services.rfp_intake import router as rfp_router
from tests.pipelines.test_rfp_intake_flow import PITCH_LINES, RFP_LINES, engine, fake_agents, minimal_pdf  # noqa: F401


BRIEFING_FIELDS = {
    "ticket_id",
    "rfp_id",
    "client_name",
    "client_country",
    "services_requested",
    "status",
    "original_filename",
    "created_at",
}
METADATA = {"client_name": "Northline Apparel", "client_country": "US", "services_requested": ["warehousing", "last_mile"]}


def rfp_ticket(ticket_id: str) -> RfpTicket:
    return RfpTicket(
        ticket_id=ticket_id,
        rfp_id=f"rfp-{ticket_id}",
        original_filename=f"{ticket_id}.pdf",
        raw_pdf_path=f"data/raw/rfp_intake/{ticket_id}.pdf",
        uploaded_by="user-1",
        created_at=datetime(2026, 7, 24, 14, 32, tzinfo=timezone.utc),
    )


def publish(ticket_id: str) -> str:
    """Publica como el worker y devuelve el id del evento en el stream."""
    events.notify_rfp_ticket_created(rfp_ticket(ticket_id), METADATA)
    entry_id, _ = events.get_event_bus().client.xrevrange(events.STREAM_KEY, count=1)[0]
    return entry_id.decode()


def frames(response: httpx.Response) -> Iterator[dict]:
    """Agrupa las líneas del stream en frames SSE (separados por una línea en blanco)."""
    frame: dict = {"comments": [], "lines": []}
    for line in response.iter_lines():
        if line == "":
            yield frame
            frame = {"comments": [], "lines": []}
            continue
        frame["lines"].append(line)
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "":
            frame["comments"].append(value)
        else:
            frame[field] = value


def next_event(stream: Iterator[dict]) -> dict:
    return next(frame for frame in stream if "event" in frame)


@pytest.fixture
def token(make_user) -> str:
    return create_access_token(make_user().id)


@pytest.fixture
def live_api() -> Iterator[str]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn no arrancó"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def open_stream(base_url: str, token: str, last_event_id: str | None = None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id
    return httpx.stream("GET", f"{base_url}/rfps/events", headers=headers, timeout=httpx.Timeout(10.0))


def test_the_stream_requires_the_backoffice_jwt():
    with TestClient(app) as client:
        assert client.get("/rfps/events").status_code == 401
        response = client.get("/rfps/events", headers={"Authorization": "Bearer no-es-un-jwt"})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_new_rfp_ticket_arrives_as_a_named_event_with_the_briefing_payload(live_api, token):
    with open_stream(live_api, token) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        # `no-transform`: sin él, el proxy de Next comprime el stream y retiene los eventos.
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert response.headers["x-accel-buffering"] == "no"
        stream = frames(response)
        # Primer frame: comentario de conexión, sin evento.
        assert next(stream)["comments"] == ["conectado"]

        entry_id = publish("tkt_0225")
        frame = next_event(stream)

    assert frame["event"] == "rfp_ticket_created"
    assert frame["id"] == entry_id
    assert frame["lines"][0] == "event: rfp_ticket_created"
    payload = json.loads(frame["data"])
    assert set(payload) == BRIEFING_FIELDS
    assert payload == {
        "ticket_id": "tkt_0225",
        "rfp_id": "rfp-tkt_0225",
        "client_name": "Northline Apparel",
        "client_country": "US",
        "services_requested": ["warehousing", "last_mile"],
        "status": "analizando",
        "original_filename": "tkt_0225.pdf",
        "created_at": "2026-07-24T14:32:00Z",
    }


def test_a_new_connection_only_receives_what_arrives_after_it(live_api, token):
    publish("tkt_old")
    with open_stream(live_api, token) as response:
        stream = frames(response)
        next(stream)
        publish("tkt_new")
        assert json.loads(next_event(stream)["data"])["ticket_id"] == "tkt_new"


def test_reconnecting_with_last_event_id_replays_only_the_missed_tickets(live_api, token):
    received_id = publish("tkt_1")
    # Mientras el cliente está desconectado entran dos RFPs.
    publish("tkt_2")
    publish("tkt_3")

    with open_stream(live_api, token, last_event_id=received_id) as response:
        stream = frames(response)
        replayed = [json.loads(next_event(stream)["data"])["ticket_id"] for _ in range(2)]

    assert replayed == ["tkt_2", "tkt_3"]


def test_idle_stream_sends_keep_alive_comments(live_api, token, monkeypatch):
    monkeypatch.setattr(rfp_router, "EVENTS_BLOCK_MS", 50)
    monkeypatch.setattr(rfp_router, "EVENTS_PING_SECONDS", 0.2)
    with open_stream(live_api, token) as response:
        stream = frames(response)
        next(stream)
        assert next(stream) == {"comments": ["ping"], "lines": [": ping"]}


def test_without_redis_the_stream_answers_503_with_an_actionable_message(token):
    server = fakeredis.FakeServer()
    server.connected = False
    events.use_event_bus(
        events.RfpEventBus(fakeredis.FakeRedis(server=server), fakeredis.FakeAsyncRedis(server=server))
    )
    with TestClient(app) as client:
        response = client.get("/rfps/events", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 503
    assert response.json() == {"detail": rfp_router.EVENTS_UNAVAILABLE_DETAIL}


# --- Origen del evento: el análisis del worker --------------------------------------------------


def test_the_event_fires_once_the_document_is_a_valid_rfp_still_analizando(engine, fake_agents):  # noqa: F811
    ticket = runner.receive_upload(engine, content=minimal_pdf(RFP_LINES), filename="luna.pdf", uploaded_by="user-1")
    seen: list[tuple[str, str | None]] = []

    def notify(detected: RfpTicket, metadata: dict) -> None:
        seen.append((detected.status, detected.rfp_id))
        events.notify_rfp_ticket_created(detected, metadata)

    assert runner.process_ticket(engine, ticket.ticket_id, on_rfp_detected=notify) == "analisis_completo"

    detail = runner.get_ticket_detail(engine, ticket.ticket_id)
    # Se avisa con el ticket aún en `analizando` y con el mismo `rfp_id` que queda guardado.
    assert seen == [("analizando", detail.metadata.rfp_id)]
    [(_, [(_, fields)])] = events.get_event_bus().client.xread({events.STREAM_KEY: events.STREAM_START})
    assert fields[b"event"] == b"rfp_ticket_created"
    payload = json.loads(fields[b"data"])
    assert payload["ticket_id"] == ticket.ticket_id and payload["rfp_id"] == detail.metadata.rfp_id
    assert payload["status"] == "analizando" and payload["client_country"] == "US"


def test_a_document_that_is_not_an_rfp_does_not_notify(engine, fake_agents):  # noqa: F811
    ticket = runner.receive_upload(engine, content=minimal_pdf(PITCH_LINES), filename="pitch.pdf", uploaded_by="user-1")
    seen: list[str] = []

    assert runner.process_ticket(engine, ticket.ticket_id, on_rfp_detected=lambda t, m: seen.append(t.ticket_id)) == (
        "descartado"
    )
    assert seen == []


def test_redis_down_in_the_worker_does_not_break_the_analysis(engine, fake_agents, caplog):  # noqa: F811
    server = fakeredis.FakeServer()
    server.connected = False
    events.use_event_bus(
        events.RfpEventBus(fakeredis.FakeRedis(server=server), fakeredis.FakeAsyncRedis(server=server))
    )
    ticket = runner.receive_upload(engine, content=minimal_pdf(RFP_LINES), filename="luna.pdf", uploaded_by="user-1")

    status = runner.process_ticket(engine, ticket.ticket_id, on_rfp_detected=events.notify_rfp_ticket_created)

    assert status == "analisis_completo"
    assert "evento rfp_ticket_created no publicado" in caplog.text
