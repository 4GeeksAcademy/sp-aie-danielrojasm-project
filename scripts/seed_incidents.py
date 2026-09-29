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


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tinydb import Query  # noqa: E402

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


def seed(csv_path: Path) -> dict[str, object]:
    inserted = 0
    already_imported = 0
    rejected: list[tuple[int, str, str]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as source, get_incidents_db() as db:
        incidents = db.table(INCIDENTS_TABLE)
        imports = db.table(SEED_IMPORTS_TABLE)
        imported_ids = {document["incident_id"] for document in imports.all()}

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

            document_id = incidents.insert(incident)
            imports.upsert(
                {"incident_id": source_id, "incident_doc_id": document_id},
                Query().incident_id == source_id,
            )
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
    except (OSError, InvalidCsvError) as error:
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
