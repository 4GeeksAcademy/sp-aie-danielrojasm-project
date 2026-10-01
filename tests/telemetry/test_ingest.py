"""Ingesta `POST /telemetry/events`: validación por evento, bulk insert en
`telemetry_events` y respuesta `{received, stored, rejected}`."""

import json
import logging
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from services.api import telemetry_models, telemetry_storage
from services.api.main import app
from services.api.routes.telemetry import get_telemetry_db
from services.api.telemetry_storage import TelemetryEventRecord
from tests.telemetry.conftest import SCHEMA


def browser_event(event_type: str = "page_viewed", **overrides: Any) -> dict[str, Any]:
    event = {
        "eventId": str(uuid4()),
        "timestamp": "2025-01-15T10:30:00.123Z",
        "sessionId": str(uuid4()),
        "userId": "anonymous",
        "event_type": event_type,
        "schemaVersion": "1.0.0",
        "requestId": str(uuid4()),
        "source": "backoffice",
        "environment": "development",
        "properties": {"route": "/inventory/products", "section": "inventory", "previous_route": None},
    }
    return {**event, **overrides}


@pytest.fixture
def client(session):
    app.dependency_overrides[get_telemetry_db] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def telemetry_log():
    """Los loggers `trackflow.*` no propagan a la raíz: se escucha el suyo."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("trackflow.telemetry")
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)


@pytest.fixture
def insert_statements(engine):
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("INSERT"):
            statements.append(statement)

    sa_event.listen(engine, "before_cursor_execute", record)
    yield statements
    sa_event.remove(engine, "before_cursor_execute", record)


def stored_rows(session) -> list[TelemetryEventRecord]:
    session.expire_all()
    return list(session.exec(select(TelemetryEventRecord)).all())


def test_valid_batch_is_stored_with_a_single_insert(client, session, insert_statements):
    events = [browser_event(), browser_event("sidebar_item_clicked", properties={"item": "inventory"})]
    events += [browser_event() for _ in range(18)]

    response = client.post("/telemetry/events", json={"events": events})

    assert response.status_code == 200
    assert response.json() == {"received": 20, "stored": 20, "rejected": 0}
    assert len(stored_rows(session)) == 20
    assert len(insert_statements) == 1


def test_event_maps_to_row_contract(client, session):
    sent = browser_event(userId=str(uuid4()))

    client.post("/telemetry/events", json={"events": [sent]})

    [row] = stored_rows(session)
    assert row.id == sent["eventId"]
    assert row.event_type == "page_viewed"
    assert row.timestamp.isoformat().startswith("2025-01-15T10:30:00.123")
    assert row.service == "backoffice"
    assert row.user_id == sent["userId"]
    assert row.session_id == sent["sessionId"]
    assert row.tags == sent["properties"]
    assert row.received_at is not None


def test_mixed_batch_stores_valid_events_and_counts_rejected(client, session):
    valid = [browser_event(), browser_event()]
    invalid = [
        browser_event(eventId="not-a-uuid"),
        browser_event(timestamp="2025-01-15T10:30:00Z"),
        browser_event(userId="ana@example.com"),
        browser_event(email="ana@example.com"),
        "no soy un objeto",
    ]

    response = client.post("/telemetry/events", json={"events": [valid[0], *invalid, valid[1]]})

    assert response.status_code == 200
    assert response.json() == {"received": 7, "stored": 2, "rejected": 5}
    assert {row.id for row in stored_rows(session)} == {event["eventId"] for event in valid}
    assert "ana@example.com" not in response.text


@pytest.mark.parametrize(
    "event",
    [
        browser_event("made_up_event"),
        # Los obligatorios solo los escribe la API: el navegador no los suplanta.
        browser_event("inbound_order_created", source="api"),
        browser_event("inbound_order_created"),
        browser_event(timestamp="2999-01-01T00:00:00.000Z"),
    ],
    ids=["unknown_event_type", "api_source", "api_only_event", "future_timestamp"],
)
def test_events_outside_the_catalog_rules_are_rejected(client, session, event):
    response = client.post("/telemetry/events", json={"events": [event, browser_event()]})

    assert response.json() == {"received": 2, "stored": 1, "rejected": 1}
    assert len(stored_rows(session)) == 1


def test_properties_outside_the_allowlist_are_dropped(client, session, telemetry_log):
    sent = browser_event(properties={"route": "/inventory", "section": "inventory", "previous_route": None,
                                     "email": "ana@example.com"})

    client.post("/telemetry/events", json={"events": [sent]})

    [row] = stored_rows(session)
    assert "email" not in row.tags
    assert row.tags["route"] == "/inventory"
    messages = " ".join(record.getMessage() for record in telemetry_log)
    assert "email" in messages and "ana@example.com" not in messages


def test_retried_batch_does_not_duplicate_rows(client, session):
    events = [browser_event(), browser_event()]

    client.post("/telemetry/events", json={"events": events})
    response = client.post("/telemetry/events", json={"events": events})

    assert response.json() == {"received": 2, "stored": 2, "rejected": 0}
    assert len(stored_rows(session)) == 2


def test_beacon_text_plain_body_is_accepted(client, session):
    # navigator.sendBeacon envía el JSON como text/plain para evitar el preflight.
    body = json.dumps({"events": [browser_event()]})

    response = client.post(
        "/telemetry/events", content=body, headers={"Content-Type": "text/plain;charset=UTF-8"}
    )

    assert response.status_code == 200
    assert response.json()["stored"] == 1


def test_response_carries_request_id_for_correlation(client):
    request_id = str(uuid4())

    response = client.post(
        "/telemetry/events", json={"events": [browser_event()]}, headers={"X-Request-Id": request_id}
    )

    assert response.headers["X-Request-Id"] == request_id


def test_empty_batch_stores_nothing(client):
    response = client.post("/telemetry/events", json={"events": []})

    assert response.status_code == 200
    assert response.json() == {"received": 0, "stored": 0, "rejected": 0}


@pytest.mark.parametrize(
    "body",
    [{"event": [browser_event()]}, {"events": "no-es-lista"}, {"events": [], "extra": 1}],
)
def test_unparseable_envelope_is_rejected_whole(client, body):
    response = client.post("/telemetry/events", json=body)

    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])


def test_malformed_json_is_rejected(client):
    response = client.post(
        "/telemetry/events", content="{no es json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


def test_batch_size_is_capped(client):
    events = [browser_event() for _ in range(telemetry_models.MAX_EVENTS_PER_BATCH + 1)]

    response = client.post("/telemetry/events", json={"events": events})

    assert response.status_code == 422


def test_store_failure_answers_503_so_the_backoffice_retries(client, monkeypatch):
    def broken(*_args):
        raise OperationalError("INSERT", {}, Exception("conexión cerrada"))

    monkeypatch.setattr("services.api.routes.telemetry.store_events", broken)

    response = client.post("/telemetry/events", json={"events": [browser_event()]})

    assert response.status_code == 503
    assert "conexión cerrada" not in response.text


def test_missing_database_answers_503():
    # Sin override ni DATABASE_URL (lo borra `isolated_environment`).
    response = TestClient(app).post("/telemetry/events", json={"events": [browser_event()]})

    assert response.status_code == 503


def test_api_buffer_flushes_emitted_events_in_one_insert(engine, session, monkeypatch, insert_statements):
    from services.api import telemetry

    monkeypatch.setattr(telemetry_storage, "get_engine", lambda: engine)
    buffer = telemetry_storage.ApiEventBuffer()
    monkeypatch.setattr(telemetry, "SINKS", [buffer])

    telemetry.emit("user_login_failed", {"reason": "wrong_password", "email_hash": None,
                                         "ip_prefix": "10.0.0.0", "ua_family": "other"})
    telemetry.emit("supplier_created", {"supplier_id": "1", "country": "ES", "status": "active"})
    buffer.flush()

    rows = stored_rows(session)
    assert {row.event_type for row in rows} == {"user_login_failed", "supplier_created"}
    assert {row.service for row in rows} == {"api"}
    assert len(insert_statements) == 1


def test_api_buffer_without_database_drops_events_quietly(monkeypatch):
    buffer = telemetry_storage.ApiEventBuffer()
    buffer(telemetry_models.TelemetryEvent.model_validate(browser_event()))

    buffer.flush()  # sin DATABASE_URL: avisa en el log y no lanza

    assert not buffer.has_pending()


def test_envelope_patterns_match_the_approved_schema():
    envelope = SCHEMA["definitions"]["envelope"]["properties"]
    definitions = SCHEMA["definitions"]

    assert telemetry_models.UUID_V4_PATTERN == definitions["uuidV4"]["pattern"]
    assert telemetry_models.TIMESTAMP_PATTERN == envelope["timestamp"]["pattern"]
    assert telemetry_models.SESSION_ID_PATTERN == envelope["sessionId"]["pattern"]
    assert telemetry_models.USER_ID_PATTERN == envelope["userId"]["pattern"]
    assert telemetry_models.EVENT_TYPE_PATTERN == envelope["event_type"]["pattern"]
    assert telemetry_models.SCHEMA_VERSION_PATTERN == envelope["schemaVersion"]["pattern"]
    model_fields = {
        field.alias or name for name, field in telemetry_models.TelemetryEvent.model_fields.items()
    }
    assert model_fields == set(envelope)
