"""Emisor de la API (`services/api/telemetry.py`): envelope, allowlist y seudonimización."""

import logging
from uuid import uuid4

import pytest

from services.api import telemetry


ERROR_PROPERTIES = {"route": "/inventory/products", "http_method": "GET", "error_class": "KeyError"}

@pytest.fixture
def telemetry_log():
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("trackflow.telemetry")
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)


def test_emit_builds_a_valid_envelope_with_request_context(emitted):
    request_id, session_id = str(uuid4()), str(uuid4())
    telemetry.bind_request(request_id, session_id)

    telemetry.emit("api_error_occurred", ERROR_PROPERTIES, user_id=str(uuid4()))

    [event] = emitted.of("api_error_occurred")
    assert event["requestId"] == request_id
    assert event["sessionId"] == session_id
    assert event["source"] == "api"
    assert event["environment"] == "development"
    assert event["schemaVersion"] == "1.0.0"


def test_keys_outside_the_allowlist_are_dropped_and_only_their_name_is_logged(
    emitted, telemetry_log
):
    telemetry.emit("api_error_occurred", {**ERROR_PROPERTIES, "email": "ana@example.com"})

    [event] = emitted.of("api_error_occurred")
    assert event["properties"] == ERROR_PROPERTIES
    warnings = [record.getMessage() for record in telemetry_log if record.levelno == logging.WARNING]
    assert any("email" in message for message in warnings)
    assert all("ana@example.com" not in message for message in warnings)


def test_unknown_event_type_is_not_emitted(emitted):
    assert telemetry.emit("stock_edited", {"quantity": 5}) is None
    assert emitted == []


def test_browser_events_cannot_be_emitted_by_the_api(emitted):
    assert telemetry.emit("session_closed", {"session_duration_s": 5}) is None
    assert emitted == []


def test_a_failing_sink_never_breaks_the_caller(emitted):
    def broken_sink(_event):
        raise RuntimeError("almacén de eventos caído")

    telemetry.SINKS.insert(0, broken_sink)
    try:
        assert telemetry.emit("api_error_occurred", ERROR_PROPERTIES) is not None
    finally:
        telemetry.SINKS.remove(broken_sink)
    assert emitted.types() == ["api_error_occurred"]


def test_environment_comes_from_the_environment_variable(emitted, monkeypatch):
    monkeypatch.setenv("TELEMETRY_ENVIRONMENT", "staging")
    telemetry.emit("api_error_occurred", ERROR_PROPERTIES)
    assert emitted.of("api_error_occurred")[0]["environment"] == "staging"


def test_telemetry_endpoint_is_read_from_the_environment(monkeypatch):
    monkeypatch.delenv("TELEMETRY_ENDPOINT", raising=False)
    assert telemetry.telemetry_endpoint() is None
    monkeypatch.setenv("TELEMETRY_ENDPOINT", "http://localhost:8000/telemetry/events")
    assert telemetry.telemetry_endpoint() == "http://localhost:8000/telemetry/events"


@pytest.mark.parametrize(
    ("header", "valid"),
    [(str(uuid4()), True), ("abc", False), (None, False), ("00000000-0000-1000-8000-000000000000", False)],
)
def test_only_uuid_v4_request_ids_are_accepted(header, valid):
    accepted = telemetry.accept_request_id(header)
    assert (accepted == header) is valid
    assert telemetry.accept_session_id(header) == (header if valid else "unknown")


def test_email_hash_is_a_keyed_truncated_hmac(monkeypatch):
    monkeypatch.setenv("TELEMETRY_HASH_KEY", "clave-de-prueba")
    first = telemetry.email_hash(" Ana@Example.com ")
    assert first == telemetry.email_hash("ana@example.com")
    assert len(first) == 16 and "ana" not in first
    monkeypatch.setenv("TELEMETRY_HASH_KEY", "otra-clave")
    assert telemetry.email_hash("ana@example.com") != first


def test_email_hash_is_null_without_key(monkeypatch):
    monkeypatch.delenv("TELEMETRY_HASH_KEY", raising=False)
    assert telemetry.email_hash("ana@example.com") is None


@pytest.mark.parametrize(
    ("host", "prefix"),
    [
        ("203.0.113.57", "203.0.113.0"),
        ("2001:db8:85a3:8d3:1319:8a2e:370:7348", "2001:db8:85a3::"),
        ("testclient", "unknown"),
        (None, "unknown"),
    ],
)
def test_ip_is_truncated(host, prefix):
    assert telemetry.ip_prefix(host) == prefix


@pytest.mark.parametrize(
    ("user_agent", "family"),
    [
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36",
            "Chrome 140",
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
            "Edge 140",
        ),
        ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0", "Firefox 128"),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.5 Safari/605.1.15",
            "Safari 17",
        ),
        ("python-httpx/0.28", "other"),
        (None, "other"),
    ],
)
def test_user_agent_is_reduced_to_family_and_major_version(user_agent, family):
    assert telemetry.ua_family(user_agent) == family
