"""Gestor de incidencias (`routes/incidents.py`, `IncidentCreate`)."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from packages.shared.incidents.domain import Branch, IncidentStatus
from services.api.incident_models import IncidentCreate, IncidentStatusUpdate
from services.api.routes.incidents import (
    IncidentValidationError,
    create_incident,
    get_incident,
    incidents_summary,
    list_incidents,
    update_incident_status,
)


def incident(**overrides) -> IncidentCreate:
    data = {
        "title": "Paquete perdido en reparto",
        "description": "El cliente no recibió el pedido 4411.",
        "category": "lost_parcel",
        "origin": "customer",
        "branch": "la_warehouse",
    }
    return IncidentCreate(**{**data, **overrides})


def list_all(**filters):
    # Los valores por defecto de la firma son objetos Query de FastAPI, y los
    # filtros llegan ya convertidos a enum (como hace FastAPI al validar la query).
    arguments = {"status_filter": None, "origin": None, "branch": None, "category": None}
    return list_incidents(**{**arguments, **filters})


def move(incident_id: int, target: str, user):
    return update_incident_status(incident_id, IncidentStatusUpdate(status=target), user)


@pytest.fixture
def operator(make_user):
    return make_user(email="operaciones@example.com")


# --- Camino feliz -----------------------------------------------------------

def test_create_starts_open_and_records_reporter(operator):
    created = create_incident(incident(), operator)
    assert created.status == "open"
    # Trazabilidad: quién la registró y cuándo.
    assert created.reported_by == "operaciones@example.com"
    assert created.created_at == created.updated_at
    assert get_incident(created.id) == created


def test_list_filters_by_status_and_branch(operator):
    first = create_incident(incident(), operator)
    create_incident(incident(branch="zaragoza_office", origin="internal"), operator)
    move(first.id, "in_progress", operator)

    assert len(list_all()) == 2
    assert [i.id for i in list_all(status_filter=IncidentStatus.IN_PROGRESS)] == [first.id]
    assert [i.branch for i in list_all(branch=Branch.ZARAGOZA_OFFICE)] == ["zaragoza_office"]


def test_summary_counts_every_dimension(operator):
    create_incident(incident(), operator)
    create_incident(incident(category="carrier_issue", branch="zaragoza_warehouse"), operator)

    summary = incidents_summary()
    assert summary.total == 2
    assert summary.by_status["open"] == 2
    assert summary.by_category["lost_parcel"] == 1
    assert summary.by_category["carrier_issue"] == 1
    assert summary.by_branch["zaragoza_warehouse"] == 1


def test_lifecycle_open_to_resolved(operator):
    created = create_incident(incident(), operator)
    assert move(created.id, "in_progress", operator).status == "in_progress"
    resolved = move(created.id, "resolved", operator)
    assert resolved.status == "resolved"
    assert resolved.updated_at > created.updated_at


# --- Casos límite -----------------------------------------------------------

def test_empty_database_gives_empty_list_and_zero_metrics():
    assert list_all() == []
    summary = incidents_summary()
    assert summary.total == 0
    # Todas las claves existen aunque no haya datos: el panel no tiene que adivinarlas.
    assert set(summary.by_status.values()) == {0}
    assert set(summary.by_branch.values()) == {0}


def test_title_of_exactly_120_characters_is_accepted():
    assert len(incident(title="x" * 120).title) == 120
    with pytest.raises(ValidationError):
        incident(title="x" * 121)


def test_title_is_trimmed_and_blank_title_rejected():
    assert incident(title="  Retraso en OnTrac  ").title == "Retraso en OnTrac"
    with pytest.raises(ValidationError):
        incident(title="   ")


# --- Modos de fallo ---------------------------------------------------------

def test_initial_status_other_than_open_is_rejected(operator):
    with pytest.raises(IncidentValidationError) as raised:
        create_incident(incident(status="resolved"), operator)
    assert raised.value.field == "status"
    assert list_all() == []


def test_disallowed_transition_explains_allowed_ones(operator):
    created = create_incident(incident(), operator)
    with pytest.raises(IncidentValidationError) as raised:
        move(created.id, "resolved", operator)
    assert "in_progress" in raised.value.message
    assert get_incident(created.id).status == "open"


@pytest.mark.parametrize("final", ["resolved", "discarded"])
def test_final_states_cannot_change(operator, final):
    created = create_incident(incident(), operator)
    if final == "resolved":
        move(created.id, "in_progress", operator)
    move(created.id, final, operator)
    with pytest.raises(IncidentValidationError) as raised:
        move(created.id, "open", operator)
    assert "final" in raised.value.message


def test_unknown_values_are_rejected_by_the_model():
    with pytest.raises(ValidationError):
        incident(category="meteorite")
    with pytest.raises(ValidationError):
        incident(reported_by="intruso@example.com")


def test_missing_incident_is_404(operator):
    with pytest.raises(HTTPException) as raised:
        get_incident(999)
    assert raised.value.status_code == 404
    with pytest.raises(HTTPException) as raised:
        move(999, "in_progress", operator)
    assert raised.value.status_code == 404
