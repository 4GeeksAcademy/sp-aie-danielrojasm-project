"""Eventos de inventario de la API: los cinco obligatorios y sus rechazos.

Los handlers se llaman como funciones con SQLite en memoria (igual que
`tests/inventory`); cada evento emitido se valida contra `event-schemas.json`.
"""

import pytest
from fastapi import HTTPException

from services.api import inventory_telemetry
from services.api.routes.inventory import (
    create_inbound_order,
    create_inventory_count,
    create_outbound_order,
    create_product,
)
from services.api.schemas import (
    InventoryCountCreate,
    SKUCreate,
    StockEntryCreate,
    StockExitCreate,
)


def new_sku(session, user, **overrides):
    data = {
        "name": "Cargador USB-C 65W",
        "sku": "TEC-CHG-065",
        "client_name": "SoundWave Electrónica",
        "category": "electronics",
        "warehouse": "ZGZ",
    }
    return create_product(SKUCreate(**{**data, **overrides}), session, user)


def receive(session, user, sku_id, quantity, warehouse="ZGZ"):
    payload = StockEntryCreate(
        sku_id=sku_id, quantity=quantity, reference="PO-2025-0001", warehouse=warehouse
    )
    return create_inbound_order(payload, session, user)


def dispatch(session, user, sku_id, quantity, warehouse="ZGZ"):
    payload = StockExitCreate(
        sku_id=sku_id,
        quantity=quantity,
        exit_type="dispatch",
        tracking_number="1Z999AA10123456784",
        warehouse=warehouse,
    )
    return create_outbound_order(payload, session, user)


def count(session, user, sku_id, counted, warehouse="ZGZ", method="cycle_count"):
    payload = InventoryCountCreate(
        sku_id=sku_id, warehouse=warehouse, counted_quantity=counted, detection_method=method
    )
    return create_inventory_count(payload, session, user)


# --- Identificadores de negocio ---------------------------------------------

@pytest.mark.parametrize(
    ("client_name", "slug"),
    [
        ("PureStep Footwear", "purestep-footwear"),
        ("SoundWave Electrónica", "soundwave-electronica"),
        ("  Glow & Co.  ", "glow-co"),
        ("L'Oréal España", "l-oreal-espana"),
        ("¿¿??", "unknown"),
    ],
)
def test_client_id_is_a_deterministic_slug(client_name, slug):
    assert inventory_telemetry.client_id(client_name) == slug


def test_warehouse_and_country_use_the_plan_vocabulary():
    assert inventory_telemetry.location("LA") == {"warehouse": "los_angeles", "country": "US"}
    assert inventory_telemetry.location("ZGZ") == {"warehouse": "zaragoza", "country": "ES"}


# --- Obligatorios -----------------------------------------------------------

def test_inbound_order_created_after_commit(session, operator, emitted):
    sku = new_sku(session, operator)
    entry = receive(session, operator, sku.id, 80)

    [event] = emitted.of("inbound_order_created")
    assert event["userId"] == operator.id
    assert event["properties"] == {
        "order_id": entry.id,
        "warehouse": "zaragoza",
        "country": "ES",
        "client_id": "soundwave-electronica",
        "product_id": "TEC-CHG-065",
        "product_category": "electronics",
        "quantity": 80,
        "user_role": "user",
    }
    # Nunca la referencia del albarán.
    assert "PO-2025-0001" not in str(event)


def test_outbound_order_created_with_stock_after(session, operator, emitted):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 120)
    exit_record = dispatch(session, operator, sku.id, 10)

    [event] = emitted.of("outbound_order_created")
    assert event["properties"]["order_id"] == exit_record.id
    assert event["properties"]["stock_after"] == 110
    assert event["properties"]["exit_type"] == "dispatch"
    # Sin datos de última milla.
    assert "1Z999AA10123456784" not in str(event)
    assert emitted.of("stock_threshold_triggered") == []


def test_stock_threshold_triggered_only_when_crossing_the_minimum(session, operator, emitted):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 60)
    dispatch(session, operator, sku.id, 5)   # 60 → 55: sigue sobre 50
    first = dispatch(session, operator, sku.id, 10)  # 55 → 45: cruza
    dispatch(session, operator, sku.id, 5)   # 45 → 40: ya estaba bajo mínimo

    [event] = emitted.of("stock_threshold_triggered")
    assert event["properties"] | {} == {
        "warehouse": "zaragoza",
        "country": "ES",
        "client_id": "soundwave-electronica",
        "product_id": "TEC-CHG-065",
        "product_category": "electronics",
        "quantity": 45,
        "threshold": 50,
        "threshold_source": "default",
        "stock_level": "low",
        "previous_quantity": 55,
        "triggering_order_id": first.id,
    }


def test_emptying_the_stock_triggers_low_and_out(session, operator, emitted):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 60)
    dispatch(session, operator, sku.id, 60)

    levels = [event["properties"]["stock_level"] for event in emitted.of("stock_threshold_triggered")]
    assert levels == ["low", "out"]


def test_client_specific_minimum(session, operator, emitted, monkeypatch):
    monkeypatch.setenv("STOCK_MIN_THRESHOLDS", '{"soundwave-electronica": 100}')
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 120)
    dispatch(session, operator, sku.id, 30)

    [event] = emitted.of("stock_threshold_triggered")
    assert event["properties"]["threshold"] == 100
    assert event["properties"]["threshold_source"] == "client_config"


def test_invalid_threshold_config_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("STOCK_MIN_THRESHOLDS", "{no es json")
    assert inventory_telemetry.min_stock_threshold("x") == (50, "default")


def test_inventory_discrepancy_detected_on_count_difference(session, operator, emitted):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 40)
    result = count(session, operator, sku.id, 37, method="audit")

    assert (result.system_quantity, result.difference) == (40, -3)
    [event] = emitted.of("inventory_discrepancy_detected")
    assert event["properties"] == {
        "count_id": result.id,
        "warehouse": "zaragoza",
        "country": "ES",
        "client_id": "soundwave-electronica",
        "product_id": "TEC-CHG-065",
        "product_category": "electronics",
        "quantity": -3,
        "system_quantity": 40,
        "counted_quantity": 37,
        "detection_method": "audit",
        "discrepancy_ratio": 0.075,
    }


def test_matching_count_emits_nothing_and_never_changes_stock(session, operator, emitted):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 40)
    count(session, operator, sku.id, 40)
    count(session, operator, sku.id, 45)

    assert len(emitted.of("inventory_discrepancy_detected")) == 1
    # El conteo no escribe stock: sigue en 40.
    assert count(session, operator, sku.id, 40).system_quantity == 40


# --- Rechazos y otros eventos de inventario ---------------------------------

def test_rejected_outbound_emits_rejection_but_no_created_event(session, operator, emitted):
    sku = new_sku(session, operator)
    receive(session, operator, sku.id, 40)

    with pytest.raises(HTTPException):
        dispatch(session, operator, sku.id, 41)

    assert emitted.of("outbound_order_created") == []
    [event] = emitted.of("outbound_order_rejected")
    assert event["properties"]["quantity"] == 41
    assert event["properties"]["available_quantity"] == 40


def test_product_created_and_duplicate_rejected(session, operator, emitted):
    new_sku(session, operator, sku="CLT-SNK-W-42", client_name="PureStep Footwear", category="fashion", warehouse="LA")
    with pytest.raises(HTTPException):
        new_sku(session, operator, sku="CLT-SNK-W-42", client_name="PureStep Footwear", category="fashion", warehouse="ZGZ")

    [created] = emitted.of("product_created")
    assert created["properties"]["warehouse"] == "los_angeles"
    [rejected] = emitted.of("product_creation_rejected")
    assert rejected["properties"] == {
        "warehouse": "zaragoza",
        "client_id": "purestep-footwear",
        "product_id": "CLT-SNK-W-42",
        "product_category": "fashion",
        "existing_warehouse": "los_angeles",
    }
