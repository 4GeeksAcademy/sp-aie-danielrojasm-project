"""Row validation for TrackFlow incident CSV exports.

Shared by the CSV analyzer (``services/api/incidents_analyzer.py``) and the
historical seed (``scripts/seed_incidents.py``) so both accept exactly the same
set of valid records.
"""

import csv
import re
from collections.abc import Iterator
from datetime import date
from typing import TextIO


REQUIRED_COLUMNS = (
    "incident_id",
    "date",
    "country",
    "customer_type",
    "tracking_number",
    "carrier",
    "category",
    "description",
    "status",
    "customer_email",
)
OPTIONAL_COLUMNS = ("satisfaction_score",)
CATEGORIES = (
    "LOST_PARCEL",
    "DELAYED_DELIVERY",
    "WRONG_ADDRESS",
    "RETURN_REQUEST",
    "DAMAGE",
)
STATUSES = ("OPEN", "CLOSED", "DISCARDED")
COUNTRIES = ("US", "ES")
CARRIERS_BY_COUNTRY = {
    "US": {"UPS", "FEDEX", "DHL_US"},
    "ES": {"MRW", "SEUR", "DHL_ES", "LOCAL_ES"},
}
INVALID_REASONS = {
    "incident_id": "Invalid or missing incident ID",
    "duplicate_incident_id": "Duplicate incident ID",
    "date": "Invalid or missing date",
    "country": "Invalid or missing country",
    "customer_type": "Invalid or missing customer type",
    "tracking_number": "Invalid tracking number",
    "carrier_country": "Carrier/country mismatch",
    "category": "Invalid or missing category",
    "description": "Invalid or missing description",
    "customer_email": "Invalid or missing email",
    "status": "Invalid or missing status",
    "satisfaction_score": "Invalid satisfaction score",
    "closed_without_score": "Closed incident, no score",
}


class InvalidCsvError(ValueError):
    """The file cannot be interpreted as a TrackFlow incidents CSV."""


def is_valid_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def validate_row(row: dict[str, str | None]) -> set[str]:
    """Return the keys of ``INVALID_REASONS`` broken by a single row."""
    issues: set[str] = set()
    values = {key: (row.get(key) or "").strip() for key in REQUIRED_COLUMNS}

    if not re.fullmatch(r"TRF-\d{6}", values["incident_id"]):
        issues.add("incident_id")
    if not is_valid_date(values["date"]):
        issues.add("date")
    if values["country"] not in COUNTRIES:
        issues.add("country")
    if values["customer_type"] not in {"B2B", "B2C"}:
        issues.add("customer_type")
    if len(values["tracking_number"]) < 8:
        issues.add("tracking_number")

    country = values["country"]
    carrier = values["carrier"]
    if country not in CARRIERS_BY_COUNTRY or carrier not in CARRIERS_BY_COUNTRY[country]:
        issues.add("carrier_country")

    if values["category"] not in CATEGORIES:
        issues.add("category")
    if len(values["description"]) < 5:
        issues.add("description")
    if "@" not in values["customer_email"]:
        issues.add("customer_email")
    if values["status"] not in STATUSES:
        issues.add("status")

    raw_score = (row.get("satisfaction_score") or "").strip()
    if raw_score:
        try:
            if not 1 <= int(raw_score) <= 5:
                issues.add("satisfaction_score")
        except ValueError:
            issues.add("satisfaction_score")
    elif values["status"] == "CLOSED":
        issues.add("closed_without_score")

    return issues


def iter_validated_rows(
    stream: TextIO,
) -> Iterator[tuple[int, dict[str, str | None], set[str]]]:
    """Yield ``(line_number, row, issues)`` for every data row of the stream.

    Checks the header first and flags repeated ``incident_id`` values after
    their first occurrence. Raises ``InvalidCsvError`` for unreadable files.
    """
    try:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames
        if not headers or not any(header.strip() for header in headers):
            raise InvalidCsvError("El fichero CSV está vacío o no tiene cabecera.")
        if len(headers) != len(set(headers)):
            raise InvalidCsvError("La cabecera del CSV contiene columnas duplicadas.")
        if any(column not in headers for column in REQUIRED_COLUMNS):
            raise InvalidCsvError(
                "El CSV no contiene todas las columnas obligatorias de TrackFlow."
            )

        seen_incident_ids: set[str] = set()
        for row in reader:
            if None in row:
                raise InvalidCsvError("Una fila del CSV tiene más valores que columnas.")
            issues = validate_row(row)
            incident_id = (row.get("incident_id") or "").strip()
            if incident_id:
                if incident_id in seen_incident_ids:
                    issues.add("duplicate_incident_id")
                else:
                    seen_incident_ids.add(incident_id)
            yield reader.line_num, row, issues
    except (csv.Error, UnicodeError) as error:
        raise InvalidCsvError("No se pudo leer el fichero como CSV UTF-8 válido.") from error
