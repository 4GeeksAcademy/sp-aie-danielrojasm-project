"""`GET /tasks/{task_id}`: estado de Celery en minúsculas, resultado y error."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from services.api.main import app
from services.api.routes import tasks as tasks_route
from services.api.security import create_access_token


TASK_ID = str(uuid4())


@pytest.fixture
def auth(make_user):
    user = make_user(email="thomas@example.com")
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def backend(monkeypatch):
    """Result backend falso: `state` y `result` de la tarea consultada."""
    stored = {"state": "PENDING", "result": None}

    class FakeResult:
        def __init__(self, task_id, app):
            self.id = task_id

        @property
        def state(self):
            if isinstance(stored["state"], Exception):
                raise stored["state"]
            return stored["state"]

        @property
        def result(self):
            return stored["result"]

    monkeypatch.setattr(tasks_route, "AsyncResult", FakeResult)
    return stored


def test_requires_a_token():
    assert TestClient(app).get(f"/tasks/{TASK_ID}").status_code == 401


@pytest.mark.parametrize(
    ("celery_state", "status"),
    [("PENDING", "pending"), ("STARTED", "started"), ("RETRY", "retry"), ("REVOKED", "failure")],
)
def test_celery_states_are_exposed_in_lowercase(auth, backend, celery_state, status):
    backend["state"] = celery_state
    backend["result"] = {"pid": 12, "hostname": "worker@host"} if celery_state == "STARTED" else None

    response = TestClient(app).get(f"/tasks/{TASK_ID}", headers=auth)

    assert response.status_code == 200
    assert response.json() == {"task_id": TASK_ID, "status": status, "result": None, "error": None}


def test_success_returns_the_result(auth, backend):
    backend.update(state="SUCCESS", result={"run_id": "r-1", "status": "completed", "attempts": 1})

    body = TestClient(app).get(f"/tasks/{TASK_ID}", headers=auth).json()

    assert body["status"] == "success"
    assert body["result"] == {"run_id": "r-1", "status": "completed", "attempts": 1}


def test_failure_returns_the_error_without_connection_details(auth, backend):
    backend.update(state="FAILURE", result=RuntimeError("could not connect to postgresql://user:pw@db:5432/x"))

    body = TestClient(app).get(f"/tasks/{TASK_ID}", headers=auth).json()

    assert body["status"] == "failure"
    assert body["result"] is None
    assert body["error"] == "RuntimeError: could not connect to <url>"


def test_task_id_must_be_a_uuid(auth, backend):
    assert TestClient(app).get("/tasks/not-a-task", headers=auth).status_code == 422


def test_without_redis_the_endpoint_answers_503(auth, backend):
    backend["state"] = RedisConnectionError("Error 10061 connecting to localhost:6379")

    response = TestClient(app).get(f"/tasks/{TASK_ID}", headers=auth)

    assert response.status_code == 503
    assert "6379" not in response.text
