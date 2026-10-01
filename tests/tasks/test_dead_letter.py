"""Tabla `task_dead_letters`: registro idempotente y respaldo cuando no se puede publicar en la cola."""

from datetime import datetime, timezone

import pytest

from services.tasks import dead_letter


FAILED_AT = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)


def record(engine, task_id: str = "task-1") -> bool:
    return dead_letter.save_dead_letter(
        engine,
        task_id=task_id,
        task_name="reporting.run_weekly_performance",
        attempts=4,
        error_type="RuntimeError",
        error_message="RuntimeError: boom",
        task_args={"run_id": "r-1"},
        failed_at=FAILED_AT,
    )


def test_a_task_is_recorded_once_even_if_the_message_is_delivered_twice(engine):
    assert record(engine) is True
    assert record(engine) is False

    [row] = dead_letter.list_dead_letters(engine)
    assert (row["task_id"], row["attempts"], row["error_message"]) == ("task-1", 4, "RuntimeError: boom")


def test_the_consumer_of_the_queue_writes_the_row(engine, eager):
    result = dead_letter.record_dead_letter.apply(
        kwargs={
            "task_id": "task-2",
            "task_name": "reporting.run_weekly_performance",
            "attempts": 4,
            "error_type": "RuntimeError",
            "error_message": "RuntimeError: boom",
            "task_args": None,
            "failed_at": FAILED_AT.isoformat(),
        }
    )

    assert result.result == {"task_id": "task-2", "recorded": True}
    assert [row["task_id"] for row in dead_letter.list_dead_letters(engine)] == ["task-2"]


def test_if_the_queue_is_unreachable_the_failure_is_written_directly(engine, monkeypatch):
    def broker_down(**_options):
        raise ConnectionError("Redis caído")

    monkeypatch.setattr(dead_letter.record_dead_letter, "apply_async", broker_down)

    dead_letter.send_to_dead_letter("task-3", "reporting.run_weekly_performance", 4, ValueError("postgresql://u:p@h/db falló"), None)

    [row] = dead_letter.list_dead_letters(engine)
    assert row["task_id"] == "task-3"
    assert row["error_message"] == "ValueError: <url> falló"  # sin credenciales


def test_without_any_storage_the_failure_is_only_logged(monkeypatch, caplog):
    monkeypatch.setattr(dead_letter.record_dead_letter, "apply_async", lambda **_: (_ for _ in ()).throw(ConnectionError()))

    dead_letter.send_to_dead_letter("task-4", "reporting.run_weekly_performance", 4, RuntimeError("boom"), None)

    assert any(record.levelname == "CRITICAL" and "task_id=task-4" in record.getMessage() for record in caplog.records)


def test_without_database_url_the_consumer_retries_instead_of_losing_the_failure(eager):
    with pytest.raises(dead_letter.DatabaseNotConfiguredError):
        dead_letter.tasks_engine()
    assert dead_letter.DatabaseNotConfiguredError in dead_letter.record_dead_letter.autoretry_for
