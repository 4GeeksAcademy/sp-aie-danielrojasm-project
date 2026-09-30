"""Eventos que dependen de la petición HTTP: edición directa del stock (405 y
422), validación del servidor, login y 500 no controlados."""

from uuid import uuid4

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from services.api import inventory_telemetry
from services.api.database import get_db
from services.api.main import app
from services.api.models import SKU
from services.api.security import create_access_token
from tests.helpers import DEFAULT_PASSWORD


@pytest.fixture
def client(engine, session, monkeypatch):
    app.dependency_overrides[get_db] = lambda: session
    # El handler de validación abre su propia sesión para resolver el SKU.
    monkeypatch.setattr(inventory_telemetry, "get_engine", lambda: engine)
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def sku(session):
    record = SKU(
        name="Sérum vitamina C 30 ml",
        sku="CSM-SRM-030",
        client_name="Glow Cosmetics",
        category="cosmetics",
        warehouse="ZGZ",
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@pytest.fixture
def auth(operator):
    return {"Authorization": f"Bearer {create_access_token(operator.id)}"}


# --- direct_stock_edit_rejected -----------------------------------------------

@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_direct_edit_of_a_product_returns_405_and_emits(client, auth, sku, operator, emitted, method):
    response = client.request(
        method, f"/inventory/products/{sku.id}", json={"current_stock": 500}, headers=auth
    )

    assert response.status_code == 405
    assert response.json() == {"detail": "El stock solo cambia con órdenes de entrada o salida."}
    [event] = emitted.of("direct_stock_edit_rejected")
    assert event["userId"] == operator.id
    assert event["properties"] == {
        "warehouse": "zaragoza",
        "country": "ES",
        "client_id": "glow-cosmetics",
        "product_id": "CSM-SRM-030",
        "product_category": "cosmetics",
        # El valor que se intentó fijar, aunque sea un DELETE con cuerpo.
        "quantity": 500,
        "attempt_type": "method_not_allowed",
        "http_method": method,
        "route": "/inventory/products/{sku_id}",
        "http_status": 405,
        "rejected_field": None,
        "target_resolved": True,
        "user_role": "user",
    }


@pytest.mark.parametrize(
    ("path", "route"),
    [
        ("/inventory/products/{id}/stock", "/inventory/products/{sku_id}/stock"),
        ("/inventory/orders", "/inventory/orders"),
        ("/inventory/orders/inbound/3", "/inventory/orders/{order_path}"),
    ],
)
def test_every_stock_resource_rejects_direct_edits(client, auth, sku, emitted, path, route):
    response = client.put(path.format(id=sku.id), headers=auth)

    assert response.status_code == 405
    [event] = emitted.of("direct_stock_edit_rejected")
    assert event["properties"]["route"] == route
    assert event["properties"]["quantity"] is None


def test_unknown_target_is_reported_as_unresolved(client, auth, emitted):
    client.delete("/inventory/products/9999", headers=auth)

    [event] = emitted.of("direct_stock_edit_rejected")
    assert event["properties"]["target_resolved"] is False
    assert event["properties"]["product_id"] is None
    assert event["properties"]["warehouse"] is None


def test_direct_edit_requires_a_session(client, sku, emitted):
    assert client.put(f"/inventory/products/{sku.id}").status_code == 401
    assert emitted == []


@pytest.mark.parametrize(
    ("field", "value", "attempt_type", "quantity"),
    [
        ("current_stock", 999, "stock_field_in_payload", 999),
        ("stock_by_warehouse", {"ZGZ": 5}, "stock_field_in_payload", None),
        ("user_uuid", str(uuid4()), "user_field_in_payload", None),
    ],
)
def test_forbidden_field_in_a_movement_is_a_direct_edit_attempt(
    client, auth, sku, emitted, field, value, attempt_type, quantity
):
    body = {"sku_id": sku.id, "quantity": 5, "reference": "PO-1", "warehouse": "ZGZ", field: value}

    response = client.post("/inventory/orders/inbound", json=body, headers=auth)

    assert response.status_code == 422
    [event] = emitted.of("direct_stock_edit_rejected")
    assert event["properties"]["attempt_type"] == attempt_type
    assert event["properties"]["rejected_field"] == field
    assert event["properties"]["quantity"] == quantity
    assert event["properties"]["http_status"] == 422
    assert event["properties"]["product_id"] == "CSM-SRM-030"
    assert emitted.of("inventory_validation_failed") == []


# --- inventory_validation_failed (servidor) -----------------------------------

def test_server_validation_failure_lists_fields_without_values(client, auth, sku, emitted):
    body = {"sku_id": sku.id, "quantity": 0, "exit_type": "dispatch", "warehouse": "ZGZ"}

    response = client.post("/inventory/orders/outbound", json=body, headers=auth)

    assert response.status_code == 422
    [event] = emitted.of("inventory_validation_failed")
    assert event["properties"]["layer"] == "server"
    assert event["properties"]["operation"] == "outbound_order"
    assert event["properties"]["product_id"] == "CSM-SRM-030"
    assert event["properties"]["client_id"] == "glow-cosmetics"
    assert "quantity" in event["properties"]["error_fields"]
    assert "greater_than" in event["properties"]["error_types"]


# --- Login --------------------------------------------------------------------

def test_login_success_and_failures_never_carry_credentials(client, make_user, emitted, monkeypatch):
    monkeypatch.setenv("TELEMETRY_HASH_KEY", "clave-de-prueba")
    user = make_user(email="ana@example.com")
    ua = {"User-Agent": "Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36"}

    client.post("/auth/login", json={"email": "ana@example.com", "password": DEFAULT_PASSWORD}, headers=ua)
    client.post("/auth/login", json={"email": "ana@example.com", "password": "otra-clave-mala"}, headers=ua)
    client.post("/auth/login", json={"email": "nadie@example.com", "password": "x"}, headers=ua)
    client.post("/auth/login", json={"email": "no-es-email"}, headers=ua)

    [succeeded] = emitted.of("user_login_succeeded")
    assert succeeded["userId"] == user.id
    assert succeeded["properties"] == {"login_method": "json", "user_role": "user", "ua_family": "Chrome 140"}
    reasons = [event["properties"]["reason"] for event in emitted.of("user_login_failed")]
    assert reasons == ["wrong_password", "unknown_account", "malformed_request"]
    serialized = str(list(emitted))
    for secret in ("ana@example.com", "nadie@example.com", DEFAULT_PASSWORD, "otra-clave-mala"):
        assert secret not in serialized


# --- api_error_occurred -------------------------------------------------------

def test_unhandled_error_emits_route_template_and_class_only(client, emitted):
    router = APIRouter()

    @router.get("/boom/{item_id}")
    def boom(item_id: int):
        raise KeyError(f"secreto-{item_id}")

    app.include_router(router)
    request_id = str(uuid4())
    try:
        response = client.get("/boom/42", headers={"X-Request-Id": request_id})
    finally:
        app.router.routes[:] = [
            route for route in app.router.routes if getattr(route, "path", "") != "/boom/{item_id}"
        ]

    assert response.status_code == 500
    [event] = emitted.of("api_error_occurred")
    assert event["requestId"] == request_id
    assert event["properties"] == {
        "route": "/boom/{item_id}",
        "http_method": "GET",
        "error_class": "KeyError",
    }
    assert "secreto" not in str(event)
