"""Motor de base de datos del pipeline.

El pipeline no importa nada de `services/` (la dependencia es siempre
`services/ → data/pipelines/`): crea su propio motor a partir de la misma
`DATABASE_URL` de Supabase (Transaction pooler) que usa la API.

En SQLite (tests y pruebas locales) el esquema `reporting` es una base de
datos adjunta: `<fichero>.reporting.db` junto a la principal, o en memoria.
"""

from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool

from data.pipelines.weekly_warehouse_client_performance.schema import SCHEMA


class DatabaseNotConfiguredError(RuntimeError):
    """Falta la cadena de conexión: el pipeline no puede leer ni escribir."""


def attach_reporting_schema(engine: Engine, path: str = ":memory:") -> None:
    """En SQLite, cada conexión adjunta la base del esquema `reporting`."""

    @event.listens_for(engine, "connect")
    def _attach(dbapi_connection, _record) -> None:
        dbapi_connection.execute(f"ATTACH DATABASE '{path}' AS {SCHEMA}")


@lru_cache(maxsize=4)
def engine_for(database_url: str) -> Engine:
    """Un motor (y un pool) por URL y proceso."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        # pool_pre_ping descarta conexiones que el pooler de Supabase haya cerrado.
        return create_engine(database_url, pool_pre_ping=True)
    if url.database in (None, "", ":memory:"):
        engine = create_engine(
            database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        attach_reporting_schema(engine)
        return engine
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    main_file = Path(url.database)
    attach_reporting_schema(engine, str(main_file.with_suffix(f".{SCHEMA}.db")).replace("\\", "/"))
    return engine
