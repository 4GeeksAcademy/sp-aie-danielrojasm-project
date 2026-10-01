"""`GET /telemetry/report`: período por defecto, validación, autenticación y caché de 60 s."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from services.api.cache import TTLCache
from services.api.main import app
from services.api.routes import telemetry_report
from services.api.security import create_access_token
from services.telemetry import analysis


@pytest.fixture
def client(engine):
    app.dependency_overrides[telemetry_report.get_report_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth(operator):
    return {"Authorization": f"Bearer {create_access_token(operator.id)}"}


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    cache = TTLCache("telemetry_report_cache", telemetry_report.REPORT_TTL_SECONDS, clock=lambda: now[0])
    monkeypatch.setattr(telemetry_report, "report_cache", cache)
    return now


@pytest.fixture
def calls(monkeypatch):
    """Ventanas con las que se ejecuta el pipeline."""
    windows: list[tuple[datetime, datetime]] = []

    def counting_build_report(engine, start, end):
        windows.append((start, end))
        return analysis.build_report(engine, start, end)

    monkeypatch.setattr(telemetry_report, "build_report", counting_build_report)
    return windows


def test_requires_a_token(client):
    assert client.get("/telemetry/report").status_code == 401


def test_defaults_to_the_last_seven_days(client, auth, calls):
    before = datetime.now(timezone.utc)

    response = client.get("/telemetry/report", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"period", "generated_at", "metrics"}
    assert set(body["metrics"]) == set(analysis.METRICS)
    [(start, end)] = calls
    assert before <= end <= datetime.now(timezone.utc)
    assert end - start == timedelta(days=7)
    assert body["period"] == {"from": start.isoformat().replace("+00:00", "Z"), "to": end.isoformat().replace("+00:00", "Z")}


def test_explicit_dates_are_read_as_utc_and_passed_to_every_metric(client, auth, calls):
    response = client.get(
        "/telemetry/report",
        params={"start_date": "2026-09-01T00:00:00", "end_date": "2026-09-08T02:00:00+02:00"},
        headers=auth,
    )

    assert response.status_code == 200
    assert calls == [
        (datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 9, 8, tzinfo=timezone.utc))
    ]
    assert response.json()["period"] == {"from": "2026-09-01T00:00:00Z", "to": "2026-09-08T00:00:00Z"}


def test_only_start_date_ends_now(client, auth, calls):
    start = datetime.now(timezone.utc) - timedelta(days=2)

    assert client.get("/telemetry/report", params={"start_date": start.isoformat()}, headers=auth).status_code == 200
    assert calls[0][0] == start
    assert calls[0][1] - start == pytest.approx(timedelta(days=2), abs=timedelta(seconds=5))


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"start_date": "2026-09-08T00:00:00Z", "end_date": "2026-09-01T00:00:00Z"}, "start_date"),
        ({"start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-01T00:00:00Z"}, "start_date"),
        ({"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-09-01T00:00:00Z"}, "end_date"),
        ({"start_date": "ayer"}, "start_date"),
    ],
)
def test_invalid_period_is_422_without_running_the_pipeline(client, auth, calls, params, field):
    response = client.get("/telemetry/report", params=params, headers=auth)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == field
    assert calls == []


def test_same_parameters_within_ttl_are_served_from_cache(client, auth, calls, clock):
    params = {"start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-08T00:00:00Z"}

    first = client.get("/telemetry/report", params=params, headers=auth).json()
    clock[0] += telemetry_report.REPORT_TTL_SECONDS - 1
    second = client.get("/telemetry/report", params=params, headers=auth).json()

    assert len(calls) == 1
    assert second == first


def test_cache_expires_after_ttl_and_keys_by_parameters(client, auth, calls, clock):
    params = {"start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-08T00:00:00Z"}

    client.get("/telemetry/report", params=params, headers=auth)
    client.get("/telemetry/report", params={**params, "end_date": "2026-09-07T00:00:00Z"}, headers=auth)
    clock[0] += telemetry_report.REPORT_TTL_SECONDS
    client.get("/telemetry/report", params=params, headers=auth)

    assert len(calls) == 3


def test_default_window_is_cached_too(client, auth, calls, clock):
    first = client.get("/telemetry/report", headers=auth).json()
    second = client.get("/telemetry/report", headers=auth).json()

    assert len(calls) == 1
    assert second["period"] == first["period"]


def test_store_failure_is_503_without_details(client, auth, monkeypatch):
    def broken(*_args):
        raise OperationalError("SELECT", {}, Exception("conexión cerrada"))

    monkeypatch.setattr(telemetry_report, "build_report", broken)

    response = client.get("/telemetry/report", headers=auth)

    assert response.status_code == 503
    assert "conexión cerrada" not in response.text


def test_missing_database_is_503(auth):
    # Sin override ni DATABASE_URL (lo borra `isolated_environment`).
    assert TestClient(app).get("/telemetry/report", headers=auth).status_code == 503
