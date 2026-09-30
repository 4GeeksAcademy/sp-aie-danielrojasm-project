"""Fixtures de telemetría: recogen los eventos emitidos y los validan contra el
JSON Schema aprobado (`docs/telemetry/event-schemas.json`)."""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft7Validator
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from services.api import telemetry
from services.api.telemetry_models import TelemetryEvent


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "telemetry" / "event-schemas.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def assert_valid_event(payload: dict[str, Any]) -> None:
    """Valida un evento serializado contra la definición de su `event_type`."""
    validator = Draft7Validator(
        {"definitions": SCHEMA["definitions"], "$ref": f"#/definitions/{payload['event_type']}"},
        format_checker=Draft7Validator.FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(payload), key=str)
    assert not errors, [error.message for error in errors]


class EmittedEvents(list[TelemetryEvent]):
    def of(self, event_type: str) -> list[dict[str, Any]]:
        """Eventos de un tipo, serializados como viajan y ya validados."""
        found = [event.model_dump(mode="json") for event in self if event.event_type == event_type]
        for payload in found:
            assert_valid_event(payload)
        return found

    def types(self) -> list[str]:
        return [event.event_type for event in self]


@pytest.fixture
def emitted() -> Iterator[EmittedEvents]:
    events = EmittedEvents()
    telemetry.SINKS.append(events.append)
    yield events
    telemetry.SINKS.remove(events.append)


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def operator(make_user):
    return make_user(email="almacen.zgz@example.com")


SkuFactory = Callable[..., Any]
