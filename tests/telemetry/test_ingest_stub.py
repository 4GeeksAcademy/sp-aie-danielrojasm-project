"""Receptor `POST /telemetry/events` (stub): valida el envelope y responde `{received: N}`."""

import json
import logging
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.api import telemetry_models
from services.api.main import app
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
def client():
    return TestClient(app)


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


def test_batch_returns_received_count_and_logs_each_event_type(client, telemetry_log):
    events = [browser_event(), browser_event("sidebar_item_clicked"), browser_event()]

    response = client.post("/telemetry/events", json={"events": events})

    assert response.status_code == 200
    assert response.json() == {"received": 3}
    message = telemetry_log[-1].getMessage()
    assert "3 eventos" in message
    assert "page_viewed, sidebar_item_clicked, page_viewed" in message


def test_beacon_text_plain_body_is_accepted(client):
    # navigator.sendBeacon envía el JSON como text/plain para evitar el preflight.
    body = json.dumps({"events": [browser_event()]})

    response = client.post(
        "/telemetry/events", content=body, headers={"Content-Type": "text/plain;charset=UTF-8"}
    )

    assert response.status_code == 200
    assert response.json() == {"received": 1}


def test_response_carries_request_id_for_correlation(client):
    request_id = str(uuid4())

    response = client.post(
        "/telemetry/events",
        json={"events": [browser_event()]},
        headers={"X-Request-Id": request_id},
    )

    assert response.headers["X-Request-Id"] == request_id


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"events": []}, "events"),
        ({"events": [browser_event(eventId="not-a-uuid")]}, "eventId"),
        ({"events": [browser_event(timestamp="2025-01-15T10:30:00Z")]}, "timestamp"),
        ({"events": [browser_event(userId="ana@example.com")]}, "userId"),
        ({"events": [browser_event(source="website")]}, "source"),
        ({"events": [browser_event(event_type="PageViewed")]}, "event_type"),
        ({"events": [browser_event(email="ana@example.com")]}, "email"),
        ({"events": [{k: v for k, v in browser_event().items() if k != "requestId"}]}, "requestId"),
        ({"event": [browser_event()]}, "event"),
    ],
)
def test_invalid_envelope_is_rejected_without_echoing_values(client, body, field):
    response = client.post("/telemetry/events", json=body)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(error["loc"][-1] == field or field in error["loc"] for error in detail)
    # Nunca se devuelve el valor recibido (podría ser un email u otro dato).
    assert "ana@example.com" not in response.text
    assert all("input" not in error for error in detail)


def test_malformed_json_is_rejected(client):
    response = client.post(
        "/telemetry/events", content="{no es json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


def test_batch_size_is_capped(client):
    events = [browser_event() for _ in range(telemetry_models.MAX_EVENTS_PER_BATCH + 1)]

    response = client.post("/telemetry/events", json={"events": events})

    assert response.status_code == 422


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
