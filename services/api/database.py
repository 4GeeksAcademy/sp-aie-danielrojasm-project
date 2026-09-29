import os
from pathlib import Path

from tinydb import TinyDB


DEFAULT_DB_PATH = Path(__file__).with_name("suppliers.json")


def get_db() -> TinyDB:
    database_path = Path(os.getenv("SUPPLIERS_DB_PATH", str(DEFAULT_DB_PATH)))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(database_path)