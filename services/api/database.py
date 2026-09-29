"""Las dos bases de datos de la API.

- TinyDB (ficheros JSON locales): usuarios y autenticación, proveedores e
  incidencias.
- Supabase (PostgreSQL, vía SQLModel): inventario — SKUs y movimientos de stock.
"""

import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine
from tinydb import TinyDB


# ---------------------------------------------------------------------------
# TinyDB
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path(__file__).with_name("suppliers.json")
DEFAULT_AUTH_DB_PATH = Path(__file__).with_name("auth.json")


def get_suppliers_db() -> TinyDB:
    database_path = Path(os.getenv("SUPPLIERS_DB_PATH", str(DEFAULT_DB_PATH)))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(database_path)


def get_auth_db() -> TinyDB:
    database_path = Path(os.getenv("AUTH_DB_PATH", str(DEFAULT_AUTH_DB_PATH)))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(database_path)

DEFAULT_INCIDENTS_DB_PATH = Path(__file__).with_name("incidents.json")
INCIDENTS_TABLE = "incidents"
SEED_IMPORTS_TABLE = "seed_imports"


def get_incidents_db() -> TinyDB:
    database_path = Path(
        os.getenv("INCIDENTS_DB_PATH", str(DEFAULT_INCIDENTS_DB_PATH))
    )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(database_path)


# ---------------------------------------------------------------------------
# Supabase (PostgreSQL) con SQLModel
# ---------------------------------------------------------------------------

class DatabaseNotConfiguredError(RuntimeError):
    """Falta `DATABASE_URL`: el inventario no está disponible."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Motor único del proceso (gestiona el pool); las sesiones son por petición."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise DatabaseNotConfiguredError(
            "Falta DATABASE_URL: configura la cadena de conexión de Supabase en .env."
        )
    # pool_pre_ping descarta conexiones que el pooler de Supabase haya cerrado.
    return create_engine(database_url, pool_pre_ping=True)


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión de SQLModel por petición."""
    with Session(get_engine()) as session:
        yield session
