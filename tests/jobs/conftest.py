"""Fixtures del job nocturno: SQLite temporal con `telemetry_events` y `job_runs`."""

import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

from services.api.telemetry_storage import TelemetryEventRecord
from services.jobs.job_runner import ensure_job_runs_table


@pytest.fixture
def engine(tmp_path) -> Iterator[Engine]:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'trackflow.db').as_posix()}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine, tables=[TelemetryEventRecord.__table__])
    ensure_job_runs_table(engine)
    yield engine
    engine.dispose()


InsertEvents = Callable[..., None]


@pytest.fixture
def insert_events(engine) -> InsertEvents:
    def _insert(*timestamps: datetime, **tags: Any) -> None:
        with Session(engine) as session:
            session.add_all(
                TelemetryEventRecord(
                    id=str(uuid.uuid4()),
                    event_type="inbound_order_created",
                    timestamp=timestamp,
                    received_at=timestamp + timedelta(seconds=1),
                    service="api",
                    user_id="user-1",
                    session_id="session-1",
                    tags=tags,
                )
                for timestamp in timestamps
            )
            session.commit()

    return _insert
