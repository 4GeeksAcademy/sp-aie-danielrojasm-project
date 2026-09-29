"""Directorio de proveedores (`routes/suppliers.py`, `SupplierCreate`)."""

from datetime import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api.models import RateUpdate, StatusUpdate, SupplierCreate
from services.api.routes.suppliers import (
    create_supplier,
    delete_supplier,
    get_supplier,
    list_suppliers,
    update_supplier_rate,
    update_supplier_status,
)


def supplier(**overrides) -> SupplierCreate:
    data = {
        "name": "MRW España",
        "country": "Spain",
        "categories": ["carrier_last_mile"],
        "rate_per_shipment": 4.9,
        "currency": "EUR",
        "status": "active",
    }
    return SupplierCreate(**{**data, **overrides})


def us_carrier(**overrides) -> SupplierCreate:
    return supplier(**{"name": "OnTrac", "country": "USA", "currency": "USD", **overrides})


# --- Camino feliz -----------------------------------------------------------

def test_create_assigns_id_and_timestamp():
    created = create_supplier(supplier())
    assert created.id >= 1
    assert isinstance(created.updated_at, datetime)
    assert get_supplier(created.id).name == "MRW España"


def test_list_filters_by_country_and_category():
    create_supplier(supplier())
    create_supplier(us_carrier())
    create_supplier(us_carrier(name="ReturnBear", categories=["reverse_logistics"]))

    # Sin filtros hay que pasar None explícitamente: los valores por defecto
    # de la firma son objetos Query de FastAPI.
    assert len(list_suppliers(country=None, category=None)) == 3
    assert {s.name for s in list_suppliers(country="USA", category=None)} == {"OnTrac", "ReturnBear"}
    assert [s.name for s in list_suppliers(country="USA", category="reverse_logistics")] == ["ReturnBear"]


def test_rate_update_refreshes_timestamp():
    created = create_supplier(supplier())
    updated = update_supplier_rate(created.id, RateUpdate(rate_per_shipment=5.25))
    assert updated.rate_per_shipment == 5.25
    # Compras usa `updated_at` para saber cuándo cambió la tarifa por última vez.
    assert updated.updated_at > created.updated_at


def test_status_change_and_delete():
    created = create_supplier(supplier())
    assert update_supplier_status(created.id, StatusUpdate(status="suspended")).status == "suspended"
    delete_supplier(created.id)
    assert list_suppliers(country=None, category=None) == []


# --- Casos límite -----------------------------------------------------------

def test_empty_directory_lists_nothing():
    assert list_suppliers(country=None, category=None) == []


def test_multi_category_supplier_matches_each_category():
    create_supplier(supplier(name="DHL Express España", categories=["carrier_last_mile", "carrier_international"]))
    for category in ("carrier_last_mile", "carrier_international"):
        assert len(list_suppliers(country=None, category=category)) == 1


def test_status_change_does_not_touch_rate_timestamp():
    # Solo la tarifa actualiza `updated_at`: suspender no es un cambio de precio.
    created = create_supplier(supplier())
    assert update_supplier_status(created.id, StatusUpdate(status="suspended")).updated_at == created.updated_at


# --- Modos de fallo ---------------------------------------------------------

@pytest.mark.parametrize(
    "overrides",
    [
        {"currency": "USD"},  # proveedor español en dólares
        {"rate_per_shipment": 0},
        {"categories": []},
        {"name": ""},
    ],
    ids=["moneda-pais", "tarifa-cero", "sin-categorias", "sin-nombre"],
)
def test_invalid_supplier_is_rejected(overrides):
    with pytest.raises(ValidationError):
        supplier(**overrides)


def test_currency_error_message_is_readable():
    with pytest.raises(ValidationError) as error:
        supplier(currency="USD")
    assert "deben usar EUR" in str(error.value)


def test_unknown_supplier_is_404_everywhere():
    for call in (
        lambda: get_supplier(999),
        lambda: update_supplier_rate(999, RateUpdate(rate_per_shipment=1)),
        lambda: update_supplier_status(999, StatusUpdate(status="active")),
        lambda: delete_supplier(999),
    ):
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 404
