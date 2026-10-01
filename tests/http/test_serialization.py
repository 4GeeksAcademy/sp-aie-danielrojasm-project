"""Contratos de serialización (docs/serialization-audit.md).

Fija qué campos devuelve cada endpoint para que un cambio en los modelos
internos no vuelva a filtrar hashes, emails o claves internas.
"""

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel
from fastapi.testclient import TestClient

from services.api.main import app
from services.api.schemas import InventoryOrderRead, SKUListItem, SKURead


PASSWORD = "correct-password"
# Rutas que siempre responden 405: el stock solo cambia con órdenes.
ROUTES_THAT_ALWAYS_REJECT = {
    "/inventory/products/{sku_id}",
    "/inventory/products/{sku_id}/stock",
    "/inventory/orders",
    "/inventory/orders/{order_path}",
}
# Rutas sin cuerpo JSON: 204 sin contenido y la descarga CSV.
ROUTES_WITHOUT_JSON_BODY = {
    ("DELETE", "/users/{user_id}"),
    ("GET", "/api/incidents/results/export"),
}
SUPPLIER = {
    "name": "MRW España",
    "country": "Spain",
    "categories": ["carrier_last_mile"],
    "rate_per_shipment": 4.1,
    "currency": "EUR",
    "status": "active",
    "service_zone": "Península",
    "contact_email": "compras@mrw.example",
    "notes": "Tarifa negociada para 2026.",
}
INCIDENT = {
    "title": "Palé dañado en muelle 3",
    "description": "Cajas aplastadas al descargar el camión de la mañana.",
    "category": "warehouse_incident",
    "origin": "branch",
    "branch": "zaragoza_warehouse",
}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, email: str = "ana@example.com") -> dict:
    response = client.post(
        "/users", json={"email": email, "password": PASSWORD, "name": "Ana"}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def auth_client(client):
    register(client)
    token = client.post(
        "/auth/login", json={"email": "ana@example.com", "password": PASSWORD}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# --- Cobertura: ninguna ruta sin contrato de salida -------------------------

def success_schema(operation: dict) -> dict | None:
    for code, response in operation["responses"].items():
        if code.startswith("2"):
            return response.get("content", {}).get("application/json", {}).get("schema")
    return None


def is_named_schema(schema: dict | None) -> bool:
    # Un `-> dict[str, object]` sale como `object` genérico; solo cuenta como
    # contrato un schema Pydantic con nombre (`$ref`) o una lista de ellos.
    if schema and schema.get("type") == "array":
        schema = schema.get("items")
    return bool(schema and "$ref" in schema)


def test_every_json_route_declares_a_pydantic_response_model():
    # Se recorre el OpenAPI (API pública) porque desde FastAPI 0.141 los
    # routers incluidos no aparecen como `APIRoute` en `app.routes`.
    operations = [
        (method.upper(), path, operation)
        for path, item in app.openapi()["paths"].items()
        for method, operation in item.items()
    ]
    rejecting = [
        (method, path, operation)
        for method, path, operation in operations
        if path in ROUTES_THAT_ALWAYS_REJECT and method in ("PUT", "PATCH", "DELETE")
    ]
    missing = [
        (method, path)
        for method, path, operation in operations
        if (method, path) not in ROUTES_WITHOUT_JSON_BODY
        and (method, path, operation) not in rejecting
        and not is_named_schema(success_schema(operation))
    ]
    # 32 rutas (el health check no se publica), el conteo físico, la ingesta y el
    # reporte de telemetría, las 3 de `/reporting` (pipeline semanal), el estado de
    # tareas de Celery (`/tasks/{task_id}`), la consulta a la base de conocimiento (`/knowledge/query`)
    # y 12 rechazos explícitos de edición directa del stock.
    assert len(operations) == 51
    assert missing == []
    # Los rechazos no tienen respuesta 2xx: su contrato es el cuerpo del 405.
    assert len(rejecting) == 12
    for _method, _path, operation in rejecting:
        error_schema = operation["responses"]["405"]["content"]["application/json"]["schema"]
        assert is_named_schema(error_schema)


def test_health_check_declares_its_schema():
    # `GET /` está fuera del OpenAPI (`include_in_schema=False`).
    (route,) = [r for r in app.routes if isinstance(r, APIRoute) and r.path == "/"]
    assert issubclass(route.response_model, BaseModel)


# --- Auth: ni contraseñas ni email en los flujos sin sesión -----------------

def test_register_returns_neither_email_nor_credentials(client):
    assert set(register(client)) == {"id", "role", "created_at"}


def test_register_rejects_fields_the_client_cannot_write(client):
    response = client.post(
        "/users", json={"email": "ana@example.com", "password": PASSWORD, "role": "admin"}
    )
    assert response.status_code == 422


def test_login_returns_only_the_token(client):
    register(client)
    response = client.post("/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert set(response.json()) == {"access_token", "token_type"}


def test_password_flows_return_a_generic_message(auth_client):
    forgot = auth_client.post("/auth/forgot-password", json={"email": "ana@example.com"})
    reset = auth_client.post(
        "/auth/reset-password", json={"token": "invalid", "new_password": "new-password-1"}
    )
    change = auth_client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "new-password-1"},
    )

    assert set(forgot.json()) == {"message"}
    assert "ana@example.com" not in forgot.text
    assert reset.status_code == 400
    assert change.json() == {"message": "Contraseña actualizada"}


def test_me_returns_own_email_and_profile_without_internal_keys(auth_client):
    me = auth_client.get("/auth/me").json()

    assert set(me) == {"id", "email", "role", "profile"}
    assert me["email"] == "ana@example.com"
    assert me["profile"] == {"name": "Ana", "phone": None, "address": None}


def test_profile_endpoints_hide_internal_keys(auth_client):
    read = auth_client.get("/profiles/me")
    written = auth_client.put("/profiles/me", json={"name": "Ana W."})
    rejected = auth_client.put("/profiles/me", json={"user_id": "someone-else"})

    assert read.json() == {"name": "Ana", "phone": None, "address": None}
    assert written.json() == {"name": "Ana W.", "phone": None, "address": None}
    assert rejected.status_code == 422


def test_user_detail_never_includes_the_password_hash(auth_client):
    user_id = auth_client.get("/auth/me").json()["id"]
    user = auth_client.get(f"/users/{user_id}").json()
    assert set(user) == {"id", "email", "role", "is_active", "created_at"}


# --- Listados ligeros frente a detalle --------------------------------------

def test_supplier_list_is_lighter_than_detail(auth_client):
    created = auth_client.post("/suppliers", json=SUPPLIER).json()
    listed = auth_client.get("/suppliers").json()[0]
    deleted = auth_client.delete(f"/suppliers/{created['id']}")

    assert {"contact_email", "notes", "updated_at"} <= set(created)
    assert set(listed) == {
        "id", "name", "country", "categories", "rate_per_shipment",
        "currency", "status", "service_zone",
    }
    assert deleted.json() == {"message": "Proveedor eliminado"}


def test_supplier_create_rejects_server_fields(auth_client):
    response = auth_client.post("/suppliers", json={**SUPPLIER, "updated_at": "2020-01-01"})
    assert response.status_code == 422


def test_incident_list_omits_reporter_email(auth_client):
    created = auth_client.post("/api/incidents", json=INCIDENT).json()
    listed = auth_client.get("/api/incidents").json()[0]

    assert created["reported_by"] == "ana@example.com"  # el detalle lo conserva
    assert set(listed) == {
        "id", "title", "description", "category", "status", "origin", "branch", "created_at",
    }


def test_inventory_list_schemas_are_flat_and_minimal():
    # El inventario necesita PostgreSQL; el contrato se comprueba en los schemas.
    assert "stock_by_warehouse" not in SKUListItem.model_fields
    assert "stock_by_warehouse" in SKURead.model_fields
    assert {"sku_code", "sku_name", "client_name"} <= set(InventoryOrderRead.model_fields)
    assert "sku" not in InventoryOrderRead.model_fields
