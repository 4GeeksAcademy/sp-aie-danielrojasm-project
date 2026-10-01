"""Flow `weekly-warehouse-client-performance` de punta a punta, con un servidor de Prefect temporal:
idempotencia, eventos tardíos, fallos parciales, reintentos, caché y log de corridas."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select

from data.pipelines import pipeline
from data.pipelines.weekly_warehouse_client_performance import runs, storage
from data.pipelines.weekly_warehouse_client_performance.schema import (
    pipeline_run_weeks,
    pipeline_runs,
    weekly_warehouse_client_performance,
)
from data.process.weekly_performance import DISCREPANCY, INBOUND, OUTBOUND, STOCKOUT
from tests.reporting.helpers import LA, ZGZ, at, closed_week, make_event


pytestmark = pytest.mark.usefixtures("prefect_server")

TABLE = weekly_warehouse_client_performance


@pytest.fixture(autouse=True)
def fast_pipeline(monkeypatch, tmp_path):
    """Sin esperas entre reintentos y con el snapshot de eval fuera del repo."""
    for name in (
        "resolve_target_weeks",
        "extract_business_events",
        "reconcile_with_domain_tables",
        "detect_capture_drop",
        "load_weekly_performance",
        "close_pipeline_run",
    ):
        task = getattr(pipeline, name)
        monkeypatch.setattr(pipeline, name, task.with_options(retry_delay_seconds=0))
    monkeypatch.setattr(pipeline, "EVAL_DIR", tmp_path / "eval")


@pytest.fixture
def week_events(insert_events):
    week = closed_week()
    return insert_events(
        make_event(INBOUND, at(week), order_id=1, quantity=40, **ZGZ),
        make_event(OUTBOUND, at(week, 2), order_id=2, exit_type="dispatch", quantity=3, **ZGZ),
        make_event(OUTBOUND, at(week, 3), order_id=3, exit_type="dispatch", quantity=1, **ZGZ),
        make_event(STOCKOUT, at(week, 3), product_id="SKU-1", stock_level="low", triggering_order_id=3, **ZGZ),
        make_event(DISCREPANCY, at(week, 4), count_id=7, **ZGZ),
        make_event(INBOUND, at(week, 5), order_id=4, quantity=12, **LA),
    )


def run_flow(**parameters):
    state = pipeline.weekly_warehouse_client_performance_flow(return_state=True, **parameters)
    return state


def published(engine) -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(select(TABLE).order_by(TABLE.c.week_start, TABLE.c.warehouse, TABLE.c.client_id))
        return [dict(row) for row in rows.mappings()]


def run_row(engine, run_id) -> dict:
    with engine.connect() as connection:
        return dict(connection.execute(select(pipeline_runs).where(pipeline_runs.c.run_id == run_id)).mappings().one())


def test_full_run_publishes_the_weekly_kpis_and_logs_the_run(engine, week_events):
    state = run_flow()

    assert state.is_completed(), state.message
    summary = state.result()
    rows = published(engine)
    assert [(row["warehouse"], row["client_id"]) for row in rows] == [
        ("los_angeles", "fashion-co"),
        ("zaragoza", "purestep-footwear"),
    ]
    zaragoza = rows[1]
    assert zaragoza["week_start"] == closed_week()
    assert (
        zaragoza["inbound_units_count"],
        zaragoza["outbound_orders_count"],
        zaragoza["stockout_events_count"],
        zaragoza["discrepancy_events_count"],
        zaragoza["discrepancy_rate"],
    ) == (40, 2, 1, 1, 0.5)

    run = run_row(engine, UUID(summary["run_id"]))
    assert run["status"] == "completed"
    assert run["phase"] == "done"
    assert run["started_at"] is not None and run["finished_at"] is not None
    assert run["duration_ms"] >= 0
    assert run["events_extracted"] == len(week_events)
    assert run["rows_upserted"] == 2
    assert run["error_type"] is None and run["error_message"] is None
    assert run["weeks_requested"] == [closed_week(3), closed_week(2), closed_week(1), closed_week()]
    assert run["source_watermark"] is not None
    assert (pipeline.EVAL_DIR / f"{summary['run_id']}.json").exists()


def test_running_twice_on_the_same_data_leaves_identical_rows(engine, week_events):
    assert run_flow().is_completed()
    first = published(engine)

    second = run_flow()

    assert second.is_completed()
    assert published(engine) == first  # mismos ids, valores y computed_at: sin duplicados
    assert second.result()["rows_changed"] == 0
    with engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(TABLE)).scalar() == 2


def test_a_late_event_recalculates_its_week_on_the_next_run(engine, week_events, insert_events):
    assert run_flow().is_completed()
    old_week = closed_week(6)  # fuera del lookback de 3 semanas
    # Llega ahora con `timestamp` de hace 6 semanas.
    insert_events(make_event(INBOUND, at(old_week), received_at=datetime.now(timezone.utc), order_id=99, quantity=7, **ZGZ))

    state = run_flow()

    assert state.is_completed()
    assert closed_week(6).isoformat() in state.result()["weeks"]
    late_rows = [row for row in published(engine) if row["week_start"] == old_week]
    assert [row["inbound_units_count"] for row in late_rows] == [7]
    assert state.result()["rows_changed"] == 1


def test_manual_run_of_one_week_does_not_move_the_watermark(engine, week_events):
    state = run_flow(week_start=closed_week())

    assert state.is_completed()
    assert state.result()["weeks"] == [closed_week().isoformat()]
    assert runs.last_watermark(engine) is None


def test_failed_optional_steps_do_not_stop_the_load(engine, week_events, monkeypatch, tmp_path):
    # Sin tablas de dominio la reconciliación falla; con EVAL_DIR bajo un fichero, el snapshot también.
    with engine.begin() as connection:
        for name in ("inventory_counts", "stock_exits", "stock_entries"):
            connection.exec_driver_sql(f"DROP TABLE {name}")
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    monkeypatch.setattr(pipeline, "EVAL_DIR", blocker / "eval")

    state = run_flow()

    assert state.is_completed(), state.message
    assert len(published(engine)) == 2
    with engine.connect() as connection:
        statuses = connection.execute(select(pipeline_run_weeks.c.reconciliation)).scalars().all()
    assert statuses and all(detail == {"status": "unavailable"} for detail in statuses)
    assert runs.get_latest_run(engine)["status"] == "completed"


def test_a_transient_load_failure_is_retried_without_duplicates(engine, week_events, monkeypatch):
    original = storage.upsert_week
    calls = {"count": 0}

    def flaky_upsert(connection, rows, computed_at):
        calls["count"] += 1
        if calls["count"] == 2:
            raise ConnectionError("conexión cortada por el pooler")
        return original(connection, rows, computed_at)

    monkeypatch.setattr(storage, "upsert_week", flaky_upsert)

    state = run_flow()

    assert state.is_completed(), state.message
    assert len(published(engine)) == 2
    with engine.connect() as connection:
        weeks = connection.execute(select(pipeline_run_weeks.c.status)).scalars().all()
    assert set(weeks) == {"loaded"}


def test_a_broken_contract_fails_the_run_before_loading(engine, week_events, monkeypatch):
    monkeypatch.setattr(pipeline, "contract_violations", lambda rows, weeks, current: ["filas repetidas"])

    state = run_flow()

    assert state.is_failed()
    assert published(engine) == []
    run = runs.get_latest_run(engine)
    assert run["status"] == "failed"
    assert run["phase"] == "validate"
    assert run["error_type"] == "ContractViolationError"
    assert run["error_message"] == "filas repetidas"
    assert run["finished_at"] is not None


def test_a_database_outage_is_recorded_without_connection_details(engine, week_events, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def outage(*_args):
        raise OperationalError("select ...", {}, Exception("could not connect to postgresql://user:secret@host"))

    monkeypatch.setattr(storage, "extract_events", outage)

    state = run_flow()

    assert state.is_failed()
    run = runs.get_latest_run(engine)
    assert (run["status"], run["phase"], run["error_type"]) == ("failed", "extract", "OperationalError")
    assert "secret" not in run["error_message"]


def test_a_second_run_cannot_start_while_one_is_active(engine, week_events):
    from data.pipelines.weekly_warehouse_client_performance.schema import ensure_schema

    ensure_schema(engine)
    pending = runs.create_pending_run(engine, triggered_by="user:1", weeks_requested=[closed_week()])

    state = run_flow()

    assert state.is_failed()
    assert published(engine) == []
    assert run_row(engine, pending)["status"] == "pending"


def test_a_pending_run_from_the_api_is_adopted_and_completed(engine, week_events):
    run_id = pipeline.trigger_weekly_performance_run(engine, closed_week(), "user:admin")

    final = pipeline.run_weekly_performance(run_id, closed_week(), "user:admin")

    assert final == "Completed"
    run = run_row(engine, run_id)
    assert (run["status"], run["trigger"], run["triggered_by"]) == ("completed", "manual", "user:admin")
    assert run["prefect_flow_run_id"] is not None


def test_the_event_preparation_is_cached_for_an_hour_on_identical_events(engine, week_events, monkeypatch):
    calls = []
    original = pipeline.clean_business_events
    monkeypatch.setattr(pipeline, "clean_business_events", lambda events, weeks: calls.append(1) or original(events, weeks))

    assert run_flow().is_completed()
    assert run_flow().is_completed()

    assert len(calls) == 1
    assert pipeline.prepare_business_events.cache_expiration == timedelta(hours=1)


def test_the_source_table_is_never_written(engine, week_events):
    with engine.connect() as connection:
        before = connection.execute(select(func.count()).select_from(storage.TELEMETRY_EVENTS)).scalar()

    assert run_flow().is_completed()

    with engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(storage.TELEMETRY_EVENTS)).scalar() == before


def test_a_capture_drop_against_the_previous_weeks_is_recorded_with_the_week(engine, insert_events):
    week, previous = closed_week(), closed_week(1)
    insert_events(
        *(make_event(INBOUND, at(previous, hour), order_id=hour, quantity=5, **ZGZ) for hour in range(1, 7)),
        make_event(INBOUND, at(week), order_id=99, quantity=5, **ZGZ),
    )

    assert run_flow(week_start=week, lookback_weeks=1).is_completed()

    with engine.connect() as connection:
        captures = dict(connection.execute(select(pipeline_run_weeks.c.week_start, pipeline_run_weeks.c.reconciliation)).all())
    assert captures[previous]["capture"] == {"events": 6, "baseline": None, "baseline_weeks": 0, "dropped": False}
    assert captures[week]["capture"] == {"events": 1, "baseline": 6.0, "baseline_weeks": 1, "dropped": True}
