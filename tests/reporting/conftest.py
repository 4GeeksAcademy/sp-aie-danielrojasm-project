"""Fixtures del pipeline de desempeño de negocio: SQLite con el esquema `reporting`
adjunto, eventos de telemetría sintéticos y un servidor de Prefect temporal."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

from data.pipelines.weekly_warehouse_client_performance.database import engine_for
from data.pipelines.weekly_warehouse_client_performance.schema import ensure_schema
from services.api import database as api_database
from services.api import models  # noqa: F401  registra stock_entries, stock_exits, inventory_counts
from services.api.telemetry_storage import TelemetryEventRecord


@pytest.fixture
def database_url(tmp_path, monkeypatch) -> Iterator[str]:
    url = f"sqlite:///{(tmp_path / 'trackflow.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    yield url
    # La API guarda su motor en `lru_cache` (p. ej. al volcar sus eventos de
    # telemetría): sin vaciarla, los tests siguientes verían esta base temporal.
    api_database.get_engine.cache_clear()


@pytest.fixture
def engine(database_url) -> Iterator[Engine]:
    """Base con `telemetry_events` y las tablas de dominio (como la de Supabase) y `reporting` adjunto."""
    engine = engine_for(database_url)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()
    engine_for.cache_clear()


InsertEvents = Callable[..., list[dict[str, Any]]]


@pytest.fixture
def insert_events(engine) -> InsertEvents:
    def _insert(*events: dict[str, Any]) -> list[dict[str, Any]]:
        with Session(engine) as session:
            session.add_all(TelemetryEventRecord(**event) for event in events)
            session.commit()
        return list(events)

    return _insert


@pytest.fixture
def reporting(engine) -> Engine:
    ensure_schema(engine)
    return engine


@pytest.fixture(scope="session")
def prefect_server(tmp_path_factory) -> Iterator[None]:
    """Servidor de Prefect temporal, con los resultados persistidos fuera del repo."""
    from prefect.settings import PREFECT_LOCAL_STORAGE_PATH, temporary_settings
    from prefect.testing.utilities import prefect_test_harness

    storage = tmp_path_factory.mktemp("prefect-results")
    with prefect_test_harness(), temporary_settings({PREFECT_LOCAL_STORAGE_PATH: storage}):
        yield
