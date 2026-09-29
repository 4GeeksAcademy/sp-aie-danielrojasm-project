"""Carga el histórico CSV del analizador como incidencias de cliente.

Uso, desde la raíz del monorepo:

    uv run python scripts/seed_incidents.py [ruta.csv]

Por defecto lee ``scripts/incidents-trackflow.csv``. Reutiliza la validación
de ``packages/shared/incidents`` (la misma que el analizador), transforma cada
fila válida al modelo del gestor y la inserta con ``origin: "customer"``.
Es idempotente: cada ``incident_id`` importado se registra en la tabla de
control ``seed_imports`` y no se vuelve a insertar.
"""

import argparse
import sys
from pathlib import Path
from typing import TextIO


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tinydb import Query, TinyDB  # noqa: E402

from packages.shared.incidents.csv_validation import (  # noqa: E402
    INVALID_REASONS,
    InvalidCsvError,
    iter_validated_rows,
)
from packages.shared.incidents.domain import (  # noqa: E402
    UnmappableRowError,
    incident_from_csv_row,
)
from services.api.database import (  # noqa: E402
    INCIDENTS_TABLE,
    SEED_IMPORTS_TABLE,
    get_incidents_db,
)


DEFAULT_CSV_PATH = REPOSITORY_ROOT / "scripts" / "incidents-trackflow.csv"


class SeedError(Exception):
    """Fallo crítico del seed con un mensaje apto para la consola."""


def check_csv_path(csv_path: Path) -> None:
    """Comprobaciones previas: el CSV existe, es un fichero y no está vacío."""
    if not csv_path.exists():
        raise SeedError(f"No existe el fichero CSV: {csv_path}")
    if not csv_path.is_file():
        raise SeedError(f"La ruta indicada no es un fichero: {csv_path}")
    if csv_path.stat().st_size == 0:
        raise SeedError(f"El fichero CSV está vacío: {csv_path}")


def _open_csv(csv_path: Path) -> TextIO:
    try:
        return csv_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as error:
        raise SeedError(f"No se pudo abrir el CSV {csv_path} ({error.strerror}).") from error


def _open_database() -> tuple[TinyDB, set[str]]:
    try:
        db = get_incidents_db()
        imported_ids = {document["incident_id"] for document in db.table(SEED_IMPORTS_TABLE).all()}
    except OSError as error:
        raise SeedError(
            f"No se pudo abrir la base de datos de incidencias ({error.strerror})."
        ) from error
    except ValueError as error:
        raise SeedError(
            "La base de datos de incidencias está dañada (JSON no válido). "
            "Restáurala o elimínala antes de volver a ejecutar el seed."
        ) from error
    return db, imported_ids


def seed(csv_path: Path) -> dict[str, object]:
    check_csv_path(csv_path)
    inserted = 0
    already_imported = 0
    rejected: list[tuple[int, str, str]] = []

    db, imported_ids = _open_database()
    with db, _open_csv(csv_path) as source:
        incidents = db.table(INCIDENTS_TABLE)
        imports = db.table(SEED_IMPORTS_TABLE)

        for line_number, row, issues in iter_validated_rows(source):
            source_id = (row.get("incident_id") or "").strip()
            if issues:
                reasons = "; ".join(INVALID_REASONS[issue] for issue in sorted(issues))
                rejected.append((line_number, source_id or "(sin id)", reasons))
                continue
            if source_id in imported_ids:
                already_imported += 1
                continue
            try:
                incident = incident_from_csv_row(row)
            except UnmappableRowError as error:
                rejected.append((line_number, source_id, str(error)))
                continue

            try:
                document_id = incidents.insert(incident)
                imports.upsert(
                    {"incident_id": source_id, "incident_doc_id": document_id},
                    Query().incident_id == source_id,
                )
            except OSError as error:
                raise SeedError(
                    f"No se pudo guardar la incidencia {source_id} ({error.strerror}). "
                    f"Insertadas antes del fallo: {inserted}; vuelve a ejecutar el seed "
                    "para completar la carga sin duplicados."
                ) from error
            imported_ids.add(source_id)
            inserted += 1

    return {"inserted": inserted, "already_imported": already_imported, "rejected": rejected}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Carga el histórico CSV de incidencias de TrackFlow en el gestor."
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"CSV de origen (por defecto {DEFAULT_CSV_PATH.relative_to(REPOSITORY_ROOT)})",
    )
    arguments = parser.parse_args()

    try:
        result = seed(arguments.csv_path)
    except (SeedError, InvalidCsvError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    rejected = result["rejected"]
    assert isinstance(rejected, list)
    print(f"Fichero: {arguments.csv_path}")
    print(f"Incidencias insertadas: {result['inserted']}")
    print(f"Ya importadas (omitidas): {result['already_imported']}")
    print(f"Registros descartados: {len(rejected)}")
    for line_number, source_id, reasons in rejected:
        print(f"  - línea {line_number} · {source_id}: {reasons}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
