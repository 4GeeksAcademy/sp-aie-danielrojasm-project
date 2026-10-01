"""Pipeline de análisis (`services/telemetry/analysis.py`) sobre `telemetry_events` en SQLite."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import insert

from services.api.telemetry_storage import TelemetryEventRecord
from services.telemetry import analysis


START = datetime(2026, 9, 28, tzinfo=timezone.utc)
END = datetime(2026, 10, 1, tzinfo=timezone.utc)


def at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


def row(event_type: str, timestamp: datetime, service: str = "backoffice", **tags: Any) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "event_type": event_type,
        "timestamp": timestamp,
        "service": service,
        "user_id": "anonymous",
        "session_id": tags.pop("session_id", "unknown"),
        "tags": tags,
    }


@pytest.fixture
def store(engine):
    def _store(*rows: dict[str, Any]) -> None:
        with engine.begin() as connection:
            connection.execute(insert(TelemetryEventRecord.__table__), list(rows))

    return _store


def test_events_per_day_groups_by_utc_day_and_service(engine, store):
    store(
        row("page_viewed", at(28, 0, 0), session_id="a"),
        row("page_viewed", at(28, 23, 59), session_id="a"),
        row("sidebar_item_clicked", at(28, 10), session_id="b"),
        row("user_login_succeeded", at(28, 9), service="api"),
        row("page_viewed", at(29, 0, 1), session_id="a"),
    )

    assert analysis.events_per_day(engine, START, END) == [
        {"date": "2026-09-28", "service": "api", "events": 1, "sessions": 1},
        {"date": "2026-09-28", "service": "backoffice", "events": 3, "sessions": 2},
        {"date": "2026-09-29", "service": "backoffice", "events": 1, "sessions": 1},
    ]


def test_window_is_start_inclusive_end_exclusive(engine, store):
    store(
        row("page_viewed", START - timedelta(microseconds=1)),
        row("page_viewed", START),
        row("page_viewed", END - timedelta(microseconds=1)),
        row("page_viewed", END),
    )

    days = analysis.events_per_day(engine, START, END)

    assert [(day["date"], day["events"]) for day in days] == [("2026-09-28", 1), ("2026-09-30", 1)]


def test_events_by_type_ranks_by_volume_with_share_and_last_seen(engine, store):
    store(
        row("page_viewed", at(28)),
        row("page_viewed", at(29, 8, 15)),
        row("page_viewed", at(29, 7)),
        row("user_login_failed", at(28), service="api"),
    )

    assert analysis.events_by_type(engine, START, END) == [
        {"event_type": "page_viewed", "events": 3, "active_days": 2, "last_seen": "2026-09-29T08:15:00Z", "share": 0.75},
        {"event_type": "user_login_failed", "events": 1, "active_days": 1, "last_seen": "2026-09-28T12:00:00Z", "share": 0.25},
    ]


def test_error_rate_uses_every_event_of_the_day_as_denominator(engine, store):
    store(
        *(row("page_viewed", at(28)) for _ in range(6)),
        row("api_call_failed", at(28)),
        row("user_login_failed", at(28), service="api"),
        row("user_login_failed", at(28), service="api"),
        row("page_viewed", at(29)),
        row("frontend_error_captured", at(29)),
    )

    assert analysis.error_rate_by_type(engine, START, END) == [
        {"date": "2026-09-28", "event_type": "user_login_failed", "error_kind": "rejected",
         "errors": 2, "total_events": 9, "error_rate": 0.2222},
        {"date": "2026-09-28", "event_type": "api_call_failed", "error_kind": "system",
         "errors": 1, "total_events": 9, "error_rate": 0.1111},
        {"date": "2026-09-29", "event_type": "frontend_error_captured", "error_kind": "system",
         "errors": 1, "total_events": 2, "error_rate": 0.5},
    ]


def test_error_rate_is_empty_without_failures(engine, store):
    store(row("page_viewed", at(28)), row("session_expired", at(28)))

    assert analysis.error_rate_by_type(engine, START, END) == []


def test_page_load_reports_p75_per_route_and_day(engine, store):
    vitals = {"ttfb_ms": 100, "fcp_ms": 300, "inp_ms": None, "cls": 0.01}
    store(
        *(row("page_load_recorded", at(28), route="/inventory", lcp_ms=lcp, **vitals) for lcp in (800, 1000, 1200, 4000)),
        row("page_load_recorded", at(28), route="/login", lcp_ms=500, **{**vitals, "inp_ms": 40}),
        row("page_load_recorded", at(28), lcp_ms=9999),  # sin ruta: no se puede atribuir
        row("page_viewed", at(28), route="/inventory"),
    )

    assert analysis.page_load_by_route(engine, START, END) == [
        {"date": "2026-09-28", "route": "/inventory", "samples": 4, "ttfb_ms_p75": 100.0, "fcp_ms_p75": 300.0,
         "lcp_ms_p75": 1900.0, "inp_ms_p75": None, "cls_p75": 0.01},
        {"date": "2026-09-28", "route": "/login", "samples": 1, "ttfb_ms_p75": 100.0, "fcp_ms_p75": 300.0,
         "lcp_ms_p75": 500.0, "inp_ms_p75": 40.0, "cls_p75": 0.01},
    ]


def test_auth_failure_rate_per_day(engine, store):
    store(
        row("user_login_failed", at(28), service="api"),
        row("user_login_failed", at(28), service="api"),
        row("user_login_succeeded", at(28), service="api"),
        row("user_login_succeeded", at(29), service="api"),
        row("page_viewed", at(29)),
    )

    assert analysis.auth_failure_rate(engine, START, END) == [
        {"date": "2026-09-28", "attempts": 3, "failed": 2, "succeeded": 1, "failure_rate": 0.6667},
        {"date": "2026-09-29", "attempts": 1, "failed": 0, "succeeded": 1, "failure_rate": 0.0},
    ]


def test_empty_window_returns_empty_lists(engine):
    assert analysis.build_report(engine, START, END) == {name: [] for name in analysis.METRICS}


def test_report_is_json_serializable_and_repeatable(engine, store):
    store(
        row("page_viewed", at(28), session_id="a"),
        row("api_error_occurred", at(28), service="api"),
        row("user_login_failed", at(29), service="api"),
        row("page_load_recorded", at(29), route="/login", ttfb_ms=90, fcp_ms=200, lcp_ms=600, inp_ms=None, cls=0),
    )

    first = analysis.build_report(engine, START, END)

    assert json.loads(json.dumps(first, allow_nan=False)) == first
    assert analysis.build_report(engine, START, END) == first
    assert all(first.values())
