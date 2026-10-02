"""Servidor MCP `mcps/trackflow_tools`: OAuth con MCP Auth, discovery, tools, mínimo privilegio, errores y logs.

El servidor corre de verdad (uvicorn en un hilo, `tests/mcp_harness.py`) y se le habla con un cliente MCP por
Streamable HTTP. Las tools de tickets llaman a la API FastAPI real (TinyDB temporal del test); el inventario, que
necesita PostgreSQL, responde con un `MockTransport` que registra cada petición.
"""

import json
import logging

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from mcps.trackflow_tools import __main__ as entrypoint
from mcps.trackflow_tools.errors import EXIT_AUTH_SERVER_UNREACHABLE, EXIT_CONFIG_ERROR
from mcps.trackflow_tools.tools import READ_OPERATIONS, TOOL_SCOPES, WRITE_OPERATIONS
from services.api.main import app as api_app
from tests.helpers import run
from tests.mcp_harness import ALL_SCOPES, SIGNING_KEY, issue_token, running_mcp_server


SKU = {
    "id": 1,
    "name": "Zapatilla blanca clásica - Talla 42",
    "sku": "CLT-SNK-W-42",
    "client_name": "PureStep Footwear",
    "category": "fashion",
    "warehouse": "LA",
    "current_stock": 278,
}
NEW_TICKET = {
    "title": "Paquete perdido en Zaragoza",
    "description": "El cliente no recibió el pedido.",
    "category": "lost_parcel",
    "origin": "customer",
    "branch": "zaragoza_office",
}


@pytest.fixture
def service_user(make_user):
    return make_user(email="mcp-service@trackflow.com")


@pytest.fixture
def mcp_url(monkeypatch, service_user):
    """Servidor MCP con la API real detrás (tickets)."""
    with running_mcp_server(monkeypatch, httpx.ASGITransport(app=api_app), service_user.id) as url:
        yield url


@pytest.fixture
def inventory_requests() -> list[httpx.Request]:
    return []


@pytest.fixture
def inventory_mcp_url(monkeypatch, inventory_requests):
    """Servidor MCP con un inventario simulado que registra cada petición que le llega."""

    def answer(request: httpx.Request) -> httpx.Response:
        inventory_requests.append(request)
        if request.url.path == "/inventory/products":
            return httpx.Response(200, json=[SKU])
        if request.url.path == "/inventory/products/1":
            return httpx.Response(200, json={**SKU, "stock_by_warehouse": {"LA": 278, "ZGZ": 0}})
        if request.url.path == "/inventory/orders":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "No existe ningún SKU con id 99."})

    with running_mcp_server(monkeypatch, httpx.MockTransport(answer)) as url:
        yield url


def client(url: str, token: str | None) -> Client:
    return Client(StreamableHttpTransport(url, auth=token))


def call(url: str, tool: str, arguments: dict, scopes: list[str] = ALL_SCOPES, **token_options):
    async def call_tool():
        async with client(url, issue_token(scopes, **token_options)) as mcp:
            return await mcp.call_tool(tool, arguments, raise_on_error=False)

    return run(call_tool())


def body(result) -> dict:
    return json.loads(result.content[0].text)


def post_mcp(url: str, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Accept": "application/json, text/event-stream", **(headers or {})},
    )


# --- OAuth (MCP Auth) ----------------------------------------------------------------------------------


def test_protected_resource_metadata_is_public_and_points_to_the_issuer(mcp_url):
    metadata = httpx.get(mcp_url.replace("/mcp", "/.well-known/oauth-protected-resource/mcp")).json()

    assert metadata["resource"] == mcp_url
    assert metadata["authorization_servers"] == ["https://auth.test/realms/trackflow"]
    assert metadata["scopes_supported"] == ALL_SCOPES


def test_without_a_token_nothing_can_be_listed_or_called(mcp_url):
    response = post_mcp(mcp_url)

    assert response.status_code == 401
    assert response.json()["error"] == "missing_auth_header"
    challenge = response.headers["WWW-Authenticate"]
    assert 'resource_metadata="' in challenge and "/.well-known/oauth-protected-resource/mcp" in challenge


@pytest.mark.parametrize(
    ("token", "error"),
    [
        ("not-a-jwt", "invalid_token"),
        (issue_token(ALL_SCOPES, expires_in=-120), "invalid_token"),
        (issue_token(ALL_SCOPES, audience="other-api"), "invalid_audience"),
        (issue_token(ALL_SCOPES, issuer="https://evil.test/realms/trackflow"), "invalid_issuer"),
    ],
    ids=["malformed", "expired", "other-audience", "other-issuer"],
)
def test_invalid_tokens_are_rejected_before_reaching_the_tools(mcp_url, token, error):
    response = post_mcp(mcp_url, {"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["error"] == error


def test_a_token_signed_with_another_key_is_rejected(mcp_url):
    from cryptography.hazmat.primitives.asymmetric import rsa

    forged = issue_token(ALL_SCOPES, key=rsa.generate_private_key(public_exponent=65537, key_size=2048))
    assert forged != issue_token(ALL_SCOPES, key=SIGNING_KEY)

    response = post_mcp(mcp_url, {"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


# --- Discovery ------------------------------------------------------------------------------------------


def test_discovery_describes_every_tool_without_reading_the_code(mcp_url):
    async def discover():
        async with client(mcp_url, issue_token(["incidents:read"])) as mcp:
            return await mcp.list_tools(), mcp.initialize_result.instructions

    listed, instructions = run(discover())
    tools = {tool.name: tool for tool in listed}

    assert set(tools) == set(TOOL_SCOPES)
    for name, tool in tools.items():
        assert tool.description and TOOL_SCOPES[name] in tool.description
        assert tool.inputSchema["properties"] and tool.outputSchema
    assert tools["get_ticket_status"].annotations.readOnlyHint is True
    assert tools["query_inventory"].annotations.readOnlyHint is True
    assert tools["create_ticket"].annotations.readOnlyHint is False
    assert set(tools["create_ticket"].inputSchema["required"]) == {"title", "description", "category", "origin", "branch"}
    assert "INVENTORY_READ_ONLY" in tools["query_inventory"].description
    assert "PATCH /api/incidents/{id}/status" in tools["update_ticket_status"].description
    assert "INSUFFICIENT_SCOPE" in instructions


# --- Tickets contra el gestor de incidencias real --------------------------------------------------------


def test_ticket_lifecycle_against_the_incident_manager(mcp_url, caplog):
    caplog.set_level(logging.INFO, logger="trackflow.mcp")

    created = call(mcp_url, "create_ticket", NEW_TICKET)
    ticket_id = body(created)["id"]
    updated = call(mcp_url, "update_ticket_status", {"ticket_id": ticket_id, "status": "in_progress"})
    read = call(mcp_url, "get_ticket_status", {"ticket_id": ticket_id}, scopes=["incidents:read"])

    assert not created.is_error and body(created)["status"] == "open"
    assert body(updated)["status"] == "in_progress"
    assert body(read)["status"] == "in_progress" and body(read)["branch"] == "zaragoza_office"
    assert "reported_by" not in body(read)
    assert (
        "tool_call tool=update_ticket_status client=trackflow-operator "
        "subject=service-account-trackflow-operator result=ok"
    ) in caplog.text


def test_status_changes_go_through_the_lifecycle_endpoint(monkeypatch):
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": 7, **NEW_TICKET, "status": "resolved", "reported_by": "ana@trackflow.com",
                                         "created_at": "2026-09-01T10:00:00Z", "updated_at": "2026-09-02T10:00:00Z"})

    with running_mcp_server(monkeypatch, httpx.MockTransport(answer)) as url:
        call(url, "update_ticket_status", {"ticket_id": 7, "status": "resolved"})

    (request,) = requests
    assert (request.method, request.url.path) == ("PATCH", "/api/incidents/7/status")
    assert json.loads(request.content) == {"status": "resolved"}


def test_a_forbidden_transition_is_a_validation_error_with_the_api_reason(mcp_url):
    ticket_id = body(call(mcp_url, "create_ticket", NEW_TICKET))["id"]

    result = call(mcp_url, "update_ticket_status", {"ticket_id": ticket_id, "status": "resolved"})

    assert result.is_error
    assert body(result)["code"] == "VALIDATION_ERROR"
    assert body(result)["errors"][0]["field"] == "status"
    assert "Transiciones permitidas" in body(result)["errors"][0]["message"]


def test_an_unknown_ticket_is_not_found(mcp_url):
    result = call(mcp_url, "get_ticket_status", {"ticket_id": 999})

    assert result.is_error and body(result)["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("tool", "arguments", "field"),
    [
        ("get_ticket_status", {"ticket_id": 0}, "ticket_id"),
        ("update_ticket_status", {"ticket_id": 1, "status": "closed"}, "status"),
        ("create_ticket", {**NEW_TICKET, "branch": "madrid"}, "branch"),
    ],
)
def test_arguments_outside_the_schema_are_validation_errors(mcp_url, tool, arguments, field):
    result = call(mcp_url, tool, arguments)

    assert result.is_error and body(result)["code"] == "VALIDATION_ERROR"
    assert body(result)["errors"][0]["field"] == field


def test_the_api_being_down_is_reported_as_upstream_unavailable(monkeypatch):
    def fail(request):
        raise httpx.ConnectError("caída")

    with running_mcp_server(monkeypatch, httpx.MockTransport(fail)) as url:
        result = call(url, "get_ticket_status", {"ticket_id": 7})

    assert result.is_error and body(result)["code"] == "UPSTREAM_UNAVAILABLE"


# --- Mínimo privilegio ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "scopes"),
    [
        ("create_ticket", NEW_TICKET, ["incidents:read"]),
        ("update_ticket_status", {"ticket_id": 1, "status": "in_progress"}, ["incidents:read", "inventory:read"]),
        ("get_ticket_status", {"ticket_id": 1}, ["inventory:read"]),
        ("query_inventory", {"operation": "list_products"}, ["incidents:read", "incidents:write"]),
    ],
)
def test_each_tool_requires_its_own_scope(mcp_url, caplog, tool, arguments, scopes):
    caplog.set_level(logging.INFO, logger="trackflow.mcp")

    result = call(mcp_url, tool, arguments, scopes=scopes, client_id="support-agent")

    assert result.is_error and body(result)["code"] == "INSUFFICIENT_SCOPE"
    assert TOOL_SCOPES[tool] in body(result)["message"]
    assert f"tool_call tool={tool} client=support-agent" in caplog.text
    assert "result=INSUFFICIENT_SCOPE" in caplog.text


# --- Inventario de solo lectura -------------------------------------------------------------------------


@pytest.mark.parametrize("operation", WRITE_OPERATIONS)
def test_inventory_writes_are_rejected_explicitly_and_never_reach_the_api(
    inventory_mcp_url, inventory_requests, operation
):
    result = call(inventory_mcp_url, "query_inventory", {"operation": operation, "sku_id": 1})

    assert result.is_error
    assert body(result)["code"] == "INVENTORY_READ_ONLY"
    assert operation in body(result)["message"]
    assert inventory_requests == []


def test_inventory_reads_answer_with_get_requests_only(inventory_mcp_url, inventory_requests):
    products = call(inventory_mcp_url, "query_inventory", {"operation": "list_products", "warehouse": "LA"})
    product = call(inventory_mcp_url, "query_inventory", {"operation": "get_product", "sku_id": 1})
    movements = call(inventory_mcp_url, "query_inventory", {"operation": "list_movements"})

    assert body(products)["products"][0]["current_stock"] == 278
    assert body(product)["product"]["stock_by_warehouse"] == {"LA": 278, "ZGZ": 0}
    assert body(movements)["movements"] == []
    assert [(request.method, request.url.path) for request in inventory_requests] == [
        ("GET", "/inventory/products"),
        ("GET", "/inventory/products/1"),
        ("GET", "/inventory/orders"),
    ]
    assert inventory_requests[0].url.params["warehouse"] == "LA"


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"operation": "get_product"}, "VALIDATION_ERROR"),
        ({"operation": "rename_warehouse"}, "VALIDATION_ERROR"),
        ({"operation": "get_product", "sku_id": 99}, "NOT_FOUND"),
    ],
)
def test_inventory_query_errors_have_their_own_code(inventory_mcp_url, arguments, code):
    result = call(inventory_mcp_url, "query_inventory", arguments)

    assert result.is_error and body(result)["code"] == code


def test_read_and_write_operations_do_not_overlap():
    assert not set(READ_OPERATIONS) & set(WRITE_OPERATIONS)


# --- Códigos de salida ----------------------------------------------------------------------------------


def test_exit_code_2_when_configuration_is_missing(monkeypatch):
    monkeypatch.delenv("MCP_OAUTH_ISSUER", raising=False)

    assert entrypoint.main() == EXIT_CONFIG_ERROR


def test_exit_code_3_when_the_oauth_provider_does_not_answer(monkeypatch):
    monkeypatch.setenv("MCP_OAUTH_ISSUER", "http://127.0.0.1:9/realms/trackflow")
    monkeypatch.setenv("MCP_RESOURCE_URL", "http://127.0.0.1:8001/mcp")
    monkeypatch.setenv("MCP_SERVICE_USER_ID", "service-user")

    assert entrypoint.main() == EXIT_AUTH_SERVER_UNREACHABLE
