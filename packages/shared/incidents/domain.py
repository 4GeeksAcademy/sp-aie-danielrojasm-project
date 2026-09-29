"""TrackFlow incident manager domain: allowed values, lifecycle and CSV mapping.

These are the only accepted values. The API models and the historical
seed import them from here instead of redefining them.
"""

from datetime import date, datetime, time, timezone
from enum import Enum


class IncidentCategory(str, Enum):
    LOST_PARCEL = "lost_parcel"
    DELIVERY_FAILURE = "delivery_failure"
    INVENTORY_DISCREPANCY = "inventory_discrepancy"
    CARRIER_ISSUE = "carrier_issue"
    RETURNS_ISSUE = "returns_issue"
    WAREHOUSE_INCIDENT = "warehouse_incident"
    SYSTEM_FAILURE = "system_failure"
    CLIENT_COMPLAINT = "client_complaint"
    OTHER = "other"


class IncidentStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DISCARDED = "discarded"


class IncidentOrigin(str, Enum):
    CUSTOMER = "customer"
    BRANCH = "branch"
    INTERNAL = "internal"


class Branch(str, Enum):
    CENTRAL = "central"
    LA_WAREHOUSE = "la_warehouse"
    LA_OFFICE = "la_office"
    ZARAGOZA_WAREHOUSE = "zaragoza_warehouse"
    ZARAGOZA_OFFICE = "zaragoza_office"


TITLE_MAX_LENGTH = 120

STATUS_TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    IncidentStatus.OPEN: frozenset({IncidentStatus.IN_PROGRESS, IncidentStatus.DISCARDED}),
    IncidentStatus.IN_PROGRESS: frozenset({IncidentStatus.RESOLVED, IncidentStatus.DISCARDED}),
    IncidentStatus.RESOLVED: frozenset(),
    IncidentStatus.DISCARDED: frozenset(),
}


def can_transition(current: IncidentStatus, target: IncidentStatus) -> bool:
    return target in STATUS_TRANSITIONS[current]


# CSV (incidents-file-analyzer) -> incident manager model.
CSV_STATUS_MAP = {
    "OPEN": IncidentStatus.OPEN,
    "CLOSED": IncidentStatus.RESOLVED,
    "DISCARDED": IncidentStatus.DISCARDED,
}
CSV_CATEGORY_MAP = {
    "LOST_PARCEL": IncidentCategory.LOST_PARCEL,
    "DELAYED_DELIVERY": IncidentCategory.CARRIER_ISSUE,
    "WRONG_ADDRESS": IncidentCategory.DELIVERY_FAILURE,
    "RETURN_REQUEST": IncidentCategory.RETURNS_ISSUE,
    "DAMAGE": IncidentCategory.CARRIER_ISSUE,
}
CSV_COUNTRY_BRANCH_MAP = {
    "US": Branch.LA_OFFICE,
    "ES": Branch.ZARAGOZA_OFFICE,
}


class UnmappableRowError(ValueError):
    """A validated CSV row cannot be expressed in the incident model."""


def incident_from_csv_row(row: dict[str, str | None]) -> dict[str, str]:
    """Transform a valid analyzer CSV row into an incident document.

    ``incident_id`` is intentionally not part of the result: it is only used by
    the seed for duplicate control.
    """
    description = row.get("description") or ""
    title = description.strip()[:TITLE_MAX_LENGTH].strip()
    if not title:
        raise UnmappableRowError("La descripción queda vacía al generar el título.")

    raw_status = (row.get("status") or "").strip()
    raw_category = (row.get("category") or "").strip()
    raw_country = (row.get("country") or "").strip()
    if raw_status not in CSV_STATUS_MAP:
        raise UnmappableRowError(f"Estado sin correspondencia: {raw_status!r}")
    if raw_category not in CSV_CATEGORY_MAP:
        raise UnmappableRowError(f"Categoría sin correspondencia: {raw_category!r}")
    if raw_country not in CSV_COUNTRY_BRANCH_MAP:
        raise UnmappableRowError(f"País sin sede asociada: {raw_country!r}")

    try:
        created_date = date.fromisoformat((row.get("date") or "").strip())
    except ValueError as error:
        raise UnmappableRowError("Fecha no válida (se espera YYYY-MM-DD).") from error
    created_at = datetime.combine(created_date, time.min, tzinfo=timezone.utc).isoformat()

    return {
        "title": title,
        "description": description,
        "category": CSV_CATEGORY_MAP[raw_category].value,
        "status": CSV_STATUS_MAP[raw_status].value,
        "origin": IncidentOrigin.CUSTOMER.value,
        "branch": CSV_COUNTRY_BRANCH_MAP[raw_country].value,
        "created_at": created_at,
        "updated_at": created_at,
    }
