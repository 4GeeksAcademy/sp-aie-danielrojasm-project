"""Checkpointer del grafo de aprobación (Parte 3) y bloqueo por ticket.

- **Dónde.** En la misma base que los tickets: PostgreSQL (Supabase) con `PostgresSaver` en producción y en Docker;
  SQLite con `SqliteSaver` cuando el engine es SQLite (tests). Nunca en memoria: la ejecución se pausa durante horas
  o días y el `resume` llega a otro proceso del worker.
- **Supabase.** El pooler en modo transacción (puerto 6543) no admite prepared statements: las conexiones de psycopg 3
  van con `prepare_threshold=None` y `autocommit=True`, como exige `PostgresSaver`.
- **Identidad.** Un hilo por ticket, `rfp-{ticket_id}` (`thread_id_for`): dos tickets nunca comparten checkpoint. Cada
  rama de departamento guarda su progreso en su propio namespace de checkpoint dentro de ese hilo.
- **Concurrencia.** Dos decisiones del mismo ticket que llegan a la vez cargarían el mismo checkpoint y una pisaría a
  la otra. `ticket_lock` las serializa: `pg_advisory_xact_lock` en PostgreSQL (válido con el pooler en modo
  transacción) y un lock de proceso en SQLite.
"""

from __future__ import annotations

import atexit
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url


logger = logging.getLogger("trackflow.rfp_intake")

_local_locks: dict[str, threading.Lock] = {}
_local_locks_guard = threading.Lock()


def thread_id_for(ticket_id: str) -> str:
    return f"rfp-{ticket_id}"


def _engine_key(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def checkpointer_for(engine: Engine) -> BaseCheckpointSaver:
    return _checkpointer(_engine_key(engine), engine.dialect.name)


@lru_cache(maxsize=8)
def _checkpointer(url: str, dialect: str) -> BaseCheckpointSaver:
    if dialect == "postgresql":
        conninfo = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
        pool = ConnectionPool(
            conninfo,
            min_size=1,
            max_size=4,
            kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
            open=True,
        )
        # Sin cerrarlo antes, el pool intenta parar sus hilos durante el apagado del intérprete y falla.
        atexit.register(pool.close)
        saver: BaseCheckpointSaver = PostgresSaver(pool)
    elif dialect == "sqlite":
        database = make_url(url).database or ":memory:"
        saver = SqliteSaver(sqlite3.connect(database, check_same_thread=False))
    else:
        raise ValueError(f"No hay checkpointer para la base {dialect}.")
    saver.setup()
    logger.info("Checkpointer de la Parte 3 listo (%s).", dialect)
    return saver


@contextmanager
def ticket_lock(engine: Engine, ticket_id: str) -> Iterator[None]:
    """Serializa las ejecuciones del grafo de aprobación de un mismo ticket (inicio y cada `resume`)."""
    key = thread_id_for(ticket_id)
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection, connection.begin():
            connection.execute(text("select pg_advisory_xact_lock(hashtext(:key))"), {"key": key})
            yield
        return
    with _local_locks_guard:
        lock = _local_locks.setdefault(f"{_engine_key(engine)}#{key}", threading.Lock())
    with lock:
        yield
