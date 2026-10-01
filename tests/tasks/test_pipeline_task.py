"""Tarea `reporting.run_weekly_performance`: éxito, reintentos con backoff y DLQ tras agotarlos.

El flow de Prefect se sustituye por una función falsa: aquí se prueba la orquestación de
Celery y el estado de `pipeline_runs`, no el ETL (ver `tests/reporting/test_pipeline_flow.py`).
"""

import logging
import subprocess
import sys
from pathlib import Path

import pytest

from data.pipelines.pipeline import trigger_weekly_performance_run
from data.pipelines.weekly_warehouse_client_performance import runs
from services.tasks import pipeline as pipeline_task
from services.tasks.dead_letter import list_dead_letters
from tests.reporting.helpers import closed_week


ROOT = Path(__file__).resolve().parents[2]


def reserve(engine) -> str:
    return str(trigger_weekly_performance_run(engine, closed_week(), "user:admin"))


@pytest.fixture
def flow_calls(monkeypatch):
    """Flow falso: adopta la corrida y la completa (o falla) como el real."""
    calls: list[tuple] = []
    outcomes: list[str] = []

    def fake_flow(run_id, week_start, triggered_by):
        calls.append((run_id, week_start, triggered_by))
        engine = pipeline_task.pipeline_engine()
        runs.start_run(engine, run_id=run_id, trigger="manual", triggered_by=triggered_by, prefect_flow_run_id=None)
        outcome = outcomes.pop(0) if outcomes else "Completed"
        if outcome == "Completed":
            runs.complete_run(engine, run_id, rows_upserted=2)
        else:
            runs.fail_run(engine, run_id, RuntimeError("Supabase no responde"))
        return outcome

    monkeypatch.setattr(pipeline_task, "run_weekly_performance", fake_flow)
    return calls, outcomes


@pytest.fixture
def countdowns(monkeypatch):
    seen: list[int] = []
    original = pipeline_task.retry_countdown

    def record(retries: int) -> int:
        seen.append(original(retries))
        return seen[-1]

    monkeypatch.setattr(pipeline_task, "retry_countdown", record)
    return seen


def test_success_adopts_the_reserved_run_and_returns_its_summary(engine, flow_calls):
    calls, _ = flow_calls
    run_id = reserve(engine)

    result = pipeline_task.run_weekly_performance_task.apply(args=[run_id, closed_week().isoformat(), "user:admin"])

    assert result.state == "SUCCESS"
    assert result.result == {"run_id": run_id, "status": "completed", "week_start": closed_week().isoformat(), "attempts": 1}
    assert [str(call[0]) for call in calls] == [run_id]
    assert runs.get_latest_run(engine)["status"] == "completed"


def test_a_transient_failure_is_retried_with_a_new_run_linked_to_the_failed_one(engine, flow_calls, countdowns):
    calls, outcomes = flow_calls
    outcomes.extend(["Failed", "Completed"])
    run_id = reserve(engine)

    result = pipeline_task.run_weekly_performance_task.apply(args=[run_id, closed_week().isoformat(), "user:admin"])

    assert result.state == "SUCCESS"
    assert result.result["attempts"] == 2
    first, second = (call[0] for call in calls)
    assert str(first) == run_id and second != first
    assert countdowns == [30]
    latest = runs.get_latest_run(engine)
    assert (latest["run_id"], latest["status"], latest["retry_of"]) == (second, "completed", first)


def test_backoff_grows_exponentially_and_reads_its_base_from_the_environment(monkeypatch):
    assert [pipeline_task.retry_countdown(n) for n in range(3)] == [30, 60, 120]
    monkeypatch.setenv("TASKS_RETRY_BACKOFF_SECONDS", "2")
    assert [pipeline_task.retry_countdown(n) for n in range(3)] == [2, 4, 8]


def test_after_three_retries_the_task_fails_and_lands_in_the_dead_letter_queue(engine, eager, flow_calls, countdowns):
    calls, outcomes = flow_calls
    outcomes.extend(["Failed"] * 4)
    run_id = reserve(engine)

    result = pipeline_task.run_weekly_performance_task.apply(args=[run_id, closed_week().isoformat(), "user:admin"])

    assert result.state == "FAILURE"
    assert isinstance(result.result, pipeline_task.PipelineRunFailedError)
    assert len(calls) == 4  # 1 ejecución + max_retries (3)
    assert countdowns == [30, 60, 120]
    [dead] = list_dead_letters(engine)
    assert dead["task_id"] == result.id
    assert dead["task_name"] == pipeline_task.TASK_NAME
    assert dead["attempts"] == 4
    assert dead["error_type"] == "PipelineRunFailedError"
    assert dead["error_message"].startswith("PipelineRunFailedError: La corrida")
    assert dead["task_args"]["run_id"] == run_id
    assert dead["task_args"]["last_run_id"] == str(calls[-1][0])
    assert dead["failed_at"] is not None
    # Ningún intento deja el lock tomado.
    assert runs.get_latest_run(engine)["status"] == "failed"


def test_a_failure_before_the_flow_closes_the_reserved_run(engine, eager, monkeypatch):
    monkeypatch.setenv("TASKS_SIMULATE_FAILURE", "1")
    monkeypatch.setattr(pipeline_task, "run_weekly_performance", lambda *_: pytest.fail("no debe ejecutar el flow"))
    run_id = reserve(engine)

    result = pipeline_task.run_weekly_performance_task.apply(args=[run_id, None, "user:admin"])

    assert result.state == "FAILURE"
    assert isinstance(result.result, pipeline_task.SimulatedFailureError)
    assert [dead["attempts"] for dead in list_dead_letters(engine)] == [4]
    with engine.connect() as connection:
        statuses = connection.execute(runs.pipeline_runs.select().with_only_columns(runs.pipeline_runs.c.status)).scalars().all()
    assert statuses == ["failed"] * 4


def test_every_attempt_is_logged_with_task_id_attempt_status_and_duration(engine, eager, flow_calls, caplog):
    _, outcomes = flow_calls
    outcomes.extend(["Failed", "Completed"])
    run_id = reserve(engine)

    with caplog.at_level(logging.INFO, logger="trackflow.tasks"):
        result = pipeline_task.run_weekly_performance_task.apply(args=[run_id, None, "user:admin"])

    lines = [(record.levelname, record.getMessage()) for record in caplog.records if record.name == "trackflow.tasks"]
    prefix = f"task_id={result.id} task={pipeline_task.TASK_NAME}"
    assert ("INFO", f"{prefix} attempt=1 status=started") in lines
    retry = next(message for level, message in lines if level == "WARNING")
    assert retry.startswith(f"{prefix} attempt=1 status=retry duration_ms=")
    assert "PipelineRunFailedError" in retry
    assert any(level == "INFO" and message.startswith(f"{prefix} attempt=2 status=success duration_ms=") for level, message in lines)


def test_final_failures_log_the_full_error_with_its_traceback(engine, eager, monkeypatch, caplog):
    monkeypatch.setenv("TASKS_SIMULATE_FAILURE", "1")
    run_id = reserve(engine)

    with caplog.at_level(logging.INFO, logger="trackflow.tasks"):
        pipeline_task.run_weekly_performance_task.apply(args=[run_id, None, "user:admin"])

    [failure] = [record for record in caplog.records if "status=failure" in record.getMessage()]
    assert failure.levelname == "ERROR"
    assert "attempt=4" in failure.getMessage()
    assert "Fallo simulado (TASKS_SIMULATE_FAILURE)" in failure.getMessage()
    assert failure.exc_info is not None
    assert any("status=dead_letter" in record.getMessage() for record in caplog.records)


def test_reserving_a_run_does_not_repeat_the_schema_ddl(engine, monkeypatch):
    """El `202` no puede pagar el DDL de `reporting` en cada disparo (~1 s contra Supabase)."""
    from data.pipelines.weekly_warehouse_client_performance import schema

    ddl: list[object] = []
    monkeypatch.setattr(schema.metadata, "create_all", lambda *args, **kwargs: ddl.append(args))

    reserve(engine)

    assert ddl == []


def test_enqueuing_does_not_subscribe_the_producer_to_the_result():
    """Con Redis caído, la suscripción pub/sub por tarea colgaba la API más de un minuto."""
    from services.tasks.celery_app import PublishOnlyRedisBackend, celery_app

    assert isinstance(celery_app.backend, PublishOnlyRedisBackend)
    assert celery_app.backend.on_task_call(producer=None, task_id="t-1") is None


def test_the_worker_modules_do_not_load_fastapi_or_the_api():
    """El worker es un proceso independiente: no importa FastAPI ni `services/api`."""
    code = (
        "import sys; import services.tasks.celery_app, services.tasks.pipeline, services.tasks.dead_letter;"
        "print([name for name in sys.modules if name == 'fastapi' or name.startswith('services.api')])"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=ROOT)

    assert output.stdout.strip() == "[]"
