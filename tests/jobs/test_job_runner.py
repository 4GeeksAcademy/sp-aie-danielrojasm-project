"""Máquina de estados de `job_runs`: transiciones, lock vía `processing` e idempotencia por fecha."""

import logging
import threading
from datetime import date, timedelta

import pytest
from sqlalchemy import update

from services.jobs import job_runner
from services.jobs.job_runner import job_runs


JOB = "nightly_export"
DAY = date(2026, 9, 30)


def test_completed_run_goes_through_every_state(engine):
    seen: list[str] = []

    def work():
        # Durante el trabajo la fila ya está en `processing` (lock tomado).
        seen.append(job_runner.list_runs(engine, JOB)[0]["status"])
        return {"rows_exported": 3}

    result = job_runner.run_job(engine, JOB, DAY, work)

    assert result.outcome == "completed"
    assert seen == ["processing"]
    run = job_runner.get_run(engine, result.run_id)
    assert run["status"] == "completed"
    assert run["target_date"] == DAY
    assert run["details"] == {"rows_exported": 3}
    assert run["error_message"] is None
    assert run["created_at"] <= run["started_at"] <= run["finished_at"]


def test_failure_leaves_the_run_failed_with_the_error_and_propagates(engine):
    def work():
        raise ValueError("telemetry_events no responde")

    with pytest.raises(ValueError):
        job_runner.run_job(engine, JOB, DAY, work)

    [run] = job_runner.list_runs(engine, JOB)
    assert run["status"] == "failed"
    assert run["error_message"] == "ValueError: telemetry_events no responde"
    assert run["finished_at"] is not None
    assert not job_runner.has_processing_lock(engine, JOB)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_interruptions_never_leave_a_zombie_processing_row(engine, interruption):
    def work():
        raise interruption()

    with pytest.raises(interruption):
        job_runner.run_job(engine, JOB, DAY, work)

    assert [run["status"] for run in job_runner.list_runs(engine, JOB)] == ["failed"]


def test_failure_is_logged_with_job_name_and_status(engine, caplog):
    def work():
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger="trackflow.jobs"), pytest.raises(RuntimeError):
        job_runner.run_job(engine, JOB, DAY, work)

    messages = [(record.levelname, record.getMessage()) for record in caplog.records]
    assert any(level == "INFO" and message.startswith(f"job={JOB} target_date={DAY} status=processing") for level, message in messages)
    assert any(level == "ERROR" and "status=failed" in message and "RuntimeError: boom" in message for level, message in messages)


def test_processing_lock_aborts_a_second_instance(engine):
    started, release = threading.Event(), threading.Event()
    second: list[job_runner.JobResult] = []
    calls: list[str] = []

    def slow_work():
        calls.append("first")
        started.set()
        assert release.wait(5)
        return {}

    def other_instance():
        assert started.wait(5)
        second.append(job_runner.run_job(engine, JOB, DAY, lambda: calls.append("second")))
        release.set()

    thread = threading.Thread(target=other_instance)
    thread.start()
    first = job_runner.run_job(engine, JOB, DAY, slow_work)
    thread.join(5)

    assert first.outcome == "completed"
    assert second[0].outcome == "skipped_locked"
    assert calls == ["first"]
    assert [run["status"] for run in job_runner.list_runs(engine, JOB)] == ["completed"]


def test_lock_is_per_job_and_released_after_failure(engine):
    with pytest.raises(RuntimeError):
        job_runner.run_job(engine, JOB, DAY, lambda: (_ for _ in ()).throw(RuntimeError("x")))

    assert job_runner.run_job(engine, JOB, DAY, lambda: {}).outcome == "completed"


def test_simultaneous_start_loses_the_race_at_the_unique_index(engine):
    """Dos instancias que pasan a la vez la comprobación del lock: solo una crea su fila."""
    job_runner.create_run(engine, JOB, DAY)

    with pytest.raises(job_runner.JobAlreadyRunningError):
        job_runner.create_run(engine, JOB, DAY)
    with pytest.raises(job_runner.JobAlreadyRunningError):
        job_runner.create_run(engine, JOB, DAY + timedelta(days=1))
    # Otro job no comparte el lock.
    job_runner.create_run(engine, "other_job", DAY)


def test_completed_date_is_not_run_twice(engine):
    calls: list[int] = []

    first = job_runner.run_job(engine, JOB, DAY, lambda: calls.append(1))
    second = job_runner.run_job(engine, JOB, DAY, lambda: calls.append(2))

    assert (first.outcome, second.outcome) == ("completed", "skipped_duplicate")
    assert calls == [1]
    assert len(job_runner.list_runs(engine, JOB, DAY)) == 1
    # Otra fecha sí se ejecuta.
    assert job_runner.run_job(engine, JOB, DAY - timedelta(days=1), lambda: None).outcome == "completed"


def test_failed_date_can_be_retried(engine):
    with pytest.raises(RuntimeError):
        job_runner.run_job(engine, JOB, DAY, lambda: (_ for _ in ()).throw(RuntimeError("x")))

    assert job_runner.run_job(engine, JOB, DAY, lambda: {}).outcome == "completed"
    assert [run["status"] for run in job_runner.list_runs(engine, JOB, DAY)] == ["failed", "completed"]
    assert job_runner.has_completed_for_date(engine, JOB, DAY)


def test_stale_processing_row_is_expired_and_frees_the_lock(engine):
    """Un proceso muerto con SIGKILL no ejecuta su `finally`: la fila caduca."""
    run_id = job_runner.create_run(engine, JOB, DAY)
    job_runner.mark_processing(engine, run_id)
    with engine.begin() as connection:
        connection.execute(
            update(job_runs).where(job_runs.c.id == run_id).values(started_at=job_runner.utc_now() - timedelta(hours=7))
        )

    result = job_runner.run_job(engine, JOB, DAY, lambda: {})

    assert result.outcome == "completed"
    stale = job_runner.get_run(engine, run_id)
    assert stale["status"] == "failed"
    assert stale["error_message"].startswith("StaleRun")


def test_recent_processing_row_is_not_expired(engine):
    run_id = job_runner.create_run(engine, JOB, DAY)
    job_runner.mark_processing(engine, run_id)

    assert job_runner.expire_stale_runs(engine, JOB) == 0
    assert job_runner.run_job(engine, JOB, DAY, lambda: {}).outcome == "skipped_locked"


def test_transitions_reject_out_of_order_moves(engine):
    run_id = job_runner.create_run(engine, JOB, DAY)

    with pytest.raises(RuntimeError):
        job_runner.mark_completed(engine, run_id)
    job_runner.mark_processing(engine, run_id)
    with pytest.raises(RuntimeError):
        job_runner.mark_processing(engine, run_id)
    job_runner.mark_completed(engine, run_id)
    # Un estado final no vuelve a `failed`.
    assert job_runner.mark_failed(engine, run_id, RuntimeError("tarde")) == 0
    assert job_runner.get_run(engine, run_id)["status"] == "completed"


def test_error_message_hides_connection_strings():
    error = RuntimeError("could not connect to postgresql://user:secret@db.supabase.co:5432/postgres")

    assert "secret" not in job_runner.describe_error(error)
    assert job_runner.describe_error(error) == "RuntimeError: could not connect to <url>"


def test_ensure_job_runs_table_is_idempotent(engine):
    job_runner.ensure_job_runs_table(engine)
    job_runner.ensure_job_runs_table(engine)

    assert job_runner.list_runs(engine, JOB) == []
