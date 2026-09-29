import argparse
import csv
import sys
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from services.api.incidents_analyzer import (  # noqa: E402
    INVALID_REASONS,
    InvalidCsvError,
    analyze_csv,
    result_rows,
)


def print_breakdown(title: str, values: dict[str, Any]) -> None:
    print(f"\n{title}")
    for name, item in values.items():
        print(f"  {name:<22} {item['count']:>5}  ({item['percentage']:>5.1f}%)")


def print_summary(summary: dict[str, Any], source: str) -> None:
    print("=" * 60)
    print("  TRACKFLOW — INCIDENT REPORT ANALYSIS")
    print(f"  Source file: {source}")
    print("=" * 60)
    print(f"\nTOTAL RECORDS IN FILE .......... {summary['total_records']}")
    print(f"  Valid records ................ {summary['valid_records']}")
    print(f"  Invalid / incomplete ......... {summary['invalid_records']}")

    print("\nINVALID RECORDS BREAKDOWN")
    for key, label in INVALID_REASONS.items():
        count = summary["invalid_breakdown"][key]["count"]
        print(f"  {label:<36} {count:>4}")

    print_breakdown("BREAKDOWN BY CATEGORY (valid records)", summary["categories"])
    print_breakdown("BREAKDOWN BY STATUS (valid records)", summary["statuses"])
    print_breakdown("BREAKDOWN BY COUNTRY (valid records)", summary["countries"])

    average = summary["average_satisfaction"]
    print("\nSATISFACTION INDEX (closed incidents)")
    print(f"  Scored incidents: {summary['scored_closed_incidents']} of {summary['closed_incidents']}")
    print(f"  Average score: {average if average is not None else 'N/A'} / 5.00")
    for score, description in enumerate(
        ("Very dissatisfied", "Dissatisfied", "Neutral", "Satisfied", "Very satisfied"),
        start=1,
    ):
        print(f"  Score {score} ({description}) .... {summary['satisfaction_scores'][str(score)]}")
    print("\n" + "=" * 60)


def export_results(summary: dict[str, Any], destination: Path) -> None:
    with destination.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("metric", "value"))
        writer.writerows(result_rows(summary))


def check_csv_path(csv_path: Path) -> str | None:
    """Devuelve un mensaje de error si la ruta no es un CSV legible."""
    if not csv_path.exists():
        return f"No existe el fichero CSV: {csv_path}"
    if not csv_path.is_file():
        return f"La ruta indicada no es un fichero: {csv_path}"
    if csv_path.stat().st_size == 0:
        return f"El fichero CSV está vacío: {csv_path}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Analiza un CSV de incidencias de TrackFlow.")
    parser.add_argument("csv_path", type=Path, help="Ruta al fichero CSV de incidencias")
    arguments = parser.parse_args()

    path_error = check_csv_path(arguments.csv_path)
    if path_error:
        print(f"Error: {path_error}", file=sys.stderr)
        return 1

    try:
        source = arguments.csv_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as error:
        print(
            f"Error: no se pudo abrir {arguments.csv_path} ({error.strerror}).",
            file=sys.stderr,
        )
        return 1
    with source:
        try:
            summary = analyze_csv(source)
        except InvalidCsvError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1

    print_summary(summary, arguments.csv_path.name)
    try:
        choice = input("¿Deseas exportar los resultados a CSV? [s / n] ").strip().lower()
    except EOFError:
        choice = "n"
    except KeyboardInterrupt:
        print("\nExportación cancelada.", file=sys.stderr)
        return 130
    if choice in {"s", "y"}:
        destination = Path("results.csv")
        try:
            export_results(summary, destination)
        except OSError as error:
            print(
                f"Error: no se pudieron exportar los resultados a {destination} "
                f"({error.strerror}). El análisis anterior sigue siendo válido.",
                file=sys.stderr,
            )
            return 1
        print(f"Resultados exportados a {destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())