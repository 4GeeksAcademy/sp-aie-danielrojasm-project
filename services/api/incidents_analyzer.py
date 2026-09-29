import csv
import re
from collections import Counter
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
    """The uploaded file cannot be interpreted as a TrackFlow incidents CSV."""


def _is_valid_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _validate_row(row: dict[str, str | None]) -> set[str]:
    issues: set[str] = set()
    values = {key: (row.get(key) or "").strip() for key in REQUIRED_COLUMNS}

    if not re.fullmatch(r"TRF-\d{6}", values["incident_id"]):
        issues.add("incident_id")
    if not _is_valid_date(values["date"]):
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
    score: int | None = None
    if raw_score:
        try:
            score = int(raw_score)
            if not 1 <= score <= 5:
                issues.add("satisfaction_score")
        except ValueError:
            issues.add("satisfaction_score")
    elif values["status"] == "CLOSED":
        issues.add("closed_without_score")

    return issues


def analyze_csv(stream: TextIO) -> dict[str, object]:
    """Validate and aggregate a CSV stream without retaining customer records."""
    try:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames
        if not headers or not any(header.strip() for header in headers):
            raise InvalidCsvError("El fichero CSV está vacío o no tiene cabecera.")
        if len(headers) != len(set(headers)):
            raise InvalidCsvError("La cabecera del CSV contiene columnas duplicadas.")

        missing_columns = [column for column in REQUIRED_COLUMNS if column not in headers]
        if missing_columns:
            raise InvalidCsvError("El CSV no contiene todas las columnas obligatorias de TrackFlow.")

        total_records = 0
        valid_records = 0
        invalid_counts: Counter[str] = Counter()
        category_counts: Counter[str] = Counter()
        status_counts: Counter[str] = Counter()
        country_counts: Counter[str] = Counter()
        satisfaction_counts: Counter[int] = Counter()
        seen_incident_ids: set[str] = set()
        satisfaction_total = 0
        scored_closed = 0
        closed_records = 0

        for row in reader:
            if None in row:
                raise InvalidCsvError("Una fila del CSV tiene más valores que columnas.")
            total_records += 1
            issues = _validate_row(row)
            incident_id = (row.get("incident_id") or "").strip()
            if incident_id:
                if incident_id in seen_incident_ids:
                    issues.add("duplicate_incident_id")
                else:
                    seen_incident_ids.add(incident_id)
            if issues:
                invalid_counts.update(issues)
                continue

            valid_records += 1
            category = (row.get("category") or "").strip()
            status = (row.get("status") or "").strip()
            country = (row.get("country") or "").strip()
            category_counts[category] += 1
            status_counts[status] += 1
            country_counts[country] += 1

            if status == "CLOSED":
                closed_records += 1
                score = int((row.get("satisfaction_score") or "").strip())
                scored_closed += 1
                satisfaction_total += score
                satisfaction_counts[score] += 1

        if total_records == 0:
            raise InvalidCsvError("El CSV no contiene registros.")

    except (csv.Error, UnicodeError) as error:
        raise InvalidCsvError("No se pudo leer el fichero como CSV UTF-8 válido.") from error

    def breakdown(values: tuple[str, ...], counts: Counter) -> dict[str, dict[str, float | int]]:
        return {
            value: {
                "count": counts[value],
                "percentage": round(counts[value] / valid_records * 100, 1) if valid_records else 0.0,
            }
            for value in values
        }

    return {
        "total_records": total_records,
        "valid_records": valid_records,
        "invalid_records": total_records - valid_records,
        "invalid_breakdown": {
            key: {"label": label, "count": invalid_counts[key]}
            for key, label in INVALID_REASONS.items()
        },
        "categories": breakdown(CATEGORIES, category_counts),
        "statuses": breakdown(STATUSES, status_counts),
        "countries": breakdown(COUNTRIES, country_counts),
        "closed_incidents": closed_records,
        "scored_closed_incidents": scored_closed,
        "average_satisfaction": round(satisfaction_total / scored_closed, 2) if scored_closed else None,
        "satisfaction_scores": {
            str(score): satisfaction_counts[score] for score in range(1, 6)
        },
    }


def result_rows(summary: dict[str, object]) -> list[tuple[str, str | int | float]]:
    """Return aggregate-only CSV rows; never includes source record values."""
    rows: list[tuple[str, str | int | float]] = [
        ("total_records", summary["total_records"]),
        ("valid_records", summary["valid_records"]),
        ("invalid_records", summary["invalid_records"]),
    ]
    invalid_breakdown = summary["invalid_breakdown"]
    assert isinstance(invalid_breakdown, dict)
    for key, item in invalid_breakdown.items():
        rows.append((f"invalid_{key}", item["count"]))

    for section in ("categories", "statuses", "countries"):
        values = summary[section]
        assert isinstance(values, dict)
        for name, item in values.items():
            rows.append((f"{section}_{name}_count", item["count"]))
            rows.append((f"{section}_{name}_percentage", item["percentage"]))

    rows.extend(
        [
            ("closed_incidents", summary["closed_incidents"]),
            ("scored_closed_incidents", summary["scored_closed_incidents"]),
            ("average_satisfaction", summary["average_satisfaction"] or ""),
        ]
    )
    scores = summary["satisfaction_scores"]
    assert isinstance(scores, dict)
    rows.extend((f"satisfaction_score_{score}", count) for score, count in scores.items())
    return rows