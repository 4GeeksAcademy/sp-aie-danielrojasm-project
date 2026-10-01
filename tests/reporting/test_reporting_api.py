"""`/reporting/*`: KPIs publicados, estado de la última corrida y disparo manual.

Los datos se cargan con las funciones de `data/pipelines` (sin Prefect): aquí se
prueba el contrato HTTP, no el flow (ver `test_pipeline_flow.py`).
"""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError as BrokerError

from data.pipelines.weekly_warehouse_client_performance import runs, storage
from data.process.weekly_performance import OUTPUT_COLUMNS
from services.api.auth_models import UserRole
from services.api.main import app
from services.api.security import create_access_token
from services.reporting import router as reporting_router
from tests.reporting.helpers import closed_week


ENDPOINTS = (
    ("GET", "/reporting/weekly-warehouse-client-performance"),
    ("GET", "/reporting/pipeline-runs/latest"),
    ("POST", "/reporting/pipeline-runs"),
)


@pytest.fixture
def client(engine):
    app.dependency_overrides[reporting_router.get_reporting_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def auth(make_user):
    user = make_user(email="thomas@example.com")
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def admin_auth(make_user):
    user = make_user(email="ana@example.com", role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def launched(monkeypatch):
    """Mensajes que el endpoint encola en Celery (sin Redis ni worker)."""
    calls = []

    def enqueue(*, args, **options):
        calls.append(tuple(args))
        return SimpleNamespace(id=f"task-{len(calls)}")

    monkeypatch.setattr(reporting_router.run_weekly_performance_task, "apply_async", enqueue)
    return calls


def publish(engine, week: date, rows: list[dict], reconciliation: str = "ok") -> UUID:
    """Una corrida completada que cargó `rows` en `week`."""
    run_id = runs.create_pending_run(engine, triggered_by="system:test", weeks_requested=[week])
    runs.start_run(engine, run_id=run_id, trigger="manual", triggered_by="system:test", prefect_flow_run_id=None)
    frame = pd.DataFrame([{"week_start": week, **row} for row in rows], columns=OUTPUT_COLUMNS)
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        storage.upsert_week(connection, frame, now)
        storage.record_week(
            connection,
            run_id,
            week,
            status="loaded",
            events_by_type={},
            reconciliation={"status": reconciliation},
            rows_upserted=len(rows),
            loaded_at=now,
        )
    runs.complete_run(engine, run_id, rows_upserted=len(rows))
    return run_id


ZGZ_ROW = {
    "warehouse": "zaragoza",
    "client_id": "purestep-footwear",
    "inbound_units_count": 4200,
    "outbound_orders_count": 980,
    "stockout_events_count": 3,
    "discrepancy_events_count": 2,
    "discrepancy_rate": 0.002,
}
LA_ROW = {**ZGZ_ROW, "warehouse": "los_angeles", "client_id": "fashion-co", "inbound_units_count": 10}


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_every_endpoint_requires_a_token(client, method, path):
    assert client.request(method, path).status_code == 401


def test_kpis_follow_the_context_contract(client, auth, reporting):
    run_id = publish(reporting, closed_week(), [ZGZ_ROW, LA_ROW], reconciliation="gap")

    response = client.get(
        "/reporting/weekly-warehouse-client-performance", params={"week_start": closed_week().isoformat()}, headers=auth
    )

    assert response.status_code == 200
    body = response.json()
    assert body["week_start"] == closed_week().isoformat()
    assert body["run_id"] == str(run_id)
    assert body["reconciliation_status"] == "gap"
    assert body["computed_at"] is not None
    assert body["entries"] == [LA_ROW, ZGZ_ROW]  # ordenadas por almacén y cliente


def test_without_week_start_returns_the_latest_loaded_week(client, auth, reporting):
    publish(reporting, closed_week(1), [ZGZ_ROW])
    publish(reporting, closed_week(), [])  # semana cargada sin actividad

    response = client.get("/reporting/weekly-warehouse-client-performance", headers=auth)

    assert response.status_code == 200
    assert response.json()["week_start"] == closed_week().isoformat()
    assert response.json()["entries"] == []


def test_a_week_that_was_never_computed_is_404(client, auth, reporting):
    publish(reporting, closed_week(), [ZGZ_ROW])

    response = client.get(
        "/reporting/weekly-warehouse-client-performance", params={"week_start": closed_week(5).isoformat()}, headers=auth
    )

    assert response.status_code == 404


def test_before_the_first_run_there_is_nothing_to_show(client, auth):
    assert client.get("/reporting/weekly-warehouse-client-performance", headers=auth).status_code == 404
    assert client.get("/reporting/pipeline-runs/latest", headers=auth).status_code == 404


def test_week_start_must_be_a_monday(client, auth):
    response = client.get(
        "/reporting/weekly-warehouse-client-performance",
        params={"week_start": (closed_week() + timedelta(days=2)).isoformat()},
        headers=auth,
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "week_start"]


def test_latest_run_exposes_its_metadata(client, auth, reporting):
    run_id = publish(reporting, closed_week(), [ZGZ_ROW])

    response = client.get("/reporting/pipeline-runs/latest", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(run_id)
    assert body["status"] == "completed"
    assert body["phase"] == "done"
    assert body["rows_upserted"] == 1
    assert body["started_at"] and body["finished_at"]
    assert body["weeks_requested"] == [closed_week().isoformat()]
    assert body["stale"] is False


def test_latest_run_is_stale_when_nothing_completed_recently(client, auth, reporting):
    runs.create_pending_run(reporting, triggered_by="user:1", weeks_requested=[closed_week()])

    body = client.get("/reporting/pipeline-runs/latest", headers=auth).json()

    assert body["status"] == "pending"
    assert body["stale"] is True


def test_only_admins_can_trigger_a_run(client, auth, launched):
    response = client.post("/reporting/pipeline-runs", headers=auth)

    assert response.status_code == 403
    assert launched == []


def test_admin_trigger_enqueues_a_task_and_answers_202_with_its_id(client, admin_auth, engine, launched):
    response = client.post("/reporting/pipeline-runs", json={"week_start": closed_week().isoformat()}, headers=admin_auth)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["task_id"] == "task-1"
    assert body["week_start"] == closed_week().isoformat()
    # Mensaje ligero: solo identificadores serializables en JSON.
    [(run_id, week_start, triggered_by)] = launched
    assert run_id == body["run_id"]
    assert week_start == closed_week().isoformat()
    assert triggered_by.startswith("user:")
    latest = runs.get_latest_run(engine)
    assert (latest["status"], latest["trigger"]) == ("pending", "manual")


def test_a_second_trigger_while_one_is_active_is_409(client, admin_auth, launched):
    first = client.post("/reporting/pipeline-runs", headers=admin_auth)

    second = client.post("/reporting/pipeline-runs", headers=admin_auth)

    assert second.status_code == 409
    assert second.json()["active_run_id"] == first.json()["run_id"]
    assert len(launched) == 1


@pytest.mark.parametrize("week_start", [lambda: closed_week() + timedelta(days=1), lambda: closed_week() + timedelta(weeks=1)])
def test_trigger_rejects_weeks_that_are_not_closed_mondays(client, admin_auth, launched, week_start):
    response = client.post("/reporting/pipeline-runs", json={"week_start": week_start().isoformat()}, headers=admin_auth)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "week_start"]
    assert launched == []


def test_without_task_queue_the_trigger_is_503_and_releases_the_lock(client, admin_auth, engine, monkeypatch):
    def broker_down(**_options):
        raise BrokerError("Error 10061 connecting to localhost:6379")

    monkeypatch.setattr(reporting_router.run_weekly_performance_task, "apply_async", broker_down)

    response = client.post("/reporting/pipeline-runs", headers=admin_auth)

    assert response.status_code == 503
    assert "localhost" not in response.text
    latest = runs.get_latest_run(engine)
    assert (latest["status"], latest["error_type"]) == ("failed", "OperationalError")


def test_the_endpoint_does_not_run_the_pipeline_in_the_api_process(client, admin_auth, launched, monkeypatch):
    import data.pipelines.pipeline as pipeline

    def must_not_run(*_args):
        raise AssertionError("La API ejecutó el flow en su proceso")

    monkeypatch.setattr(pipeline, "run_weekly_performance", must_not_run)

    response = client.post("/reporting/pipeline-runs", headers=admin_auth)

    assert response.status_code == 202
    assert len(launched) == 1


def test_without_database_the_endpoints_answer_503(auth):
    # Sin override: `DATABASE_URL` no está configurada en los tests.
    response = TestClient(app).get("/reporting/pipeline-runs/latest", headers=auth)

    assert response.status_code == 503
