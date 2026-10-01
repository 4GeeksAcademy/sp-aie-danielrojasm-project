"""Fixtures de la cola de tareas: SQLite temporal con `reporting` adjunto y Celery en modo eager
(las tareas corren en el proceso del test, sin Redis ni worker)."""

from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine

from data.pipelines.weekly_warehouse_client_performance.database import engine_for
from data.pipelines.weekly_warehouse_client_performance.schema import ensure_schema
from services.api import database as api_database
from services.tasks.celery_app import celery_app


@pytest.fixture
def engine(tmp_path, monkeypatch) -> Iterator[Engine]:
    url = f"sqlite:///{(tmp_path / 'trackflow.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = engine_for(url)
    ensure_schema(engine)
    yield engine
    engine.dispose()
    engine_for.cache_clear()
    api_database.get_engine.cache_clear()


@pytest.fixture
def eager() -> Iterator[None]:
    """`apply_async` (p. ej. el mensaje a la DLQ) se ejecuta en el acto."""
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = False
