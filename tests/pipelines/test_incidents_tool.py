"""Tool `get_ticket` del agente: lee el ticket como cliente del servidor MCP, nunca contra la API de incidencias.

El servidor MCP corre de verdad en un hilo (`tests/mcp_harness.py`) y el token OAuth del agente lo firma la clave de
prueba en lugar de pedirlo a Keycloak. Detrás del servidor, un `MockTransport` hace de gestor de incidencias y
registra cada petición.
"""

import asyncio
import contextlib
import time

import httpx
import pytest
from pydantic import ValidationError

from services.support_agent.tools import incidents
from services.support_agent.tools.incidents import TicketQuery, get_ticket
from tests.mcp_harness import issue_token, running_mcp_server


INCIDENT = {
    "id": 482,
    "title": "Paquete perdido en Zaragoza",
    "description": "El cliente no recibió el pedido.",
    "category": "lost_parcel",
    "status": "in_progress",
    "origin": "customer",
    "branch": "zaragoza_office",
    "reported_by": "ana@trackflow.com",
    "created_at": "2026-09-01T10:00:00+00:00",
    "updated_at": "2026-09-02T12:00:00+00:00",
}


@pytest.fixture
def agent_token(monkeypatch):
    """Token del cliente `support-agent`: solo `incidents:read`, como en el realm de Keycloak."""
    scopes: list[list[str]] = []

    async def fetch_access_token():
        scopes.append([incidents.MCP_TICKET_SCOPE])
        return issue_token([incidents.MCP_TICKET_SCOPE], client_id="support-agent")

    monkeypatch.setattr(incidents, "fetch_access_token", fetch_access_token)
    return scopes


@pytest.fixture
def mcp_server(monkeypatch):
    """Arranca el servidor MCP con `handler` como gestor de incidencias y apunta el agente a él."""
    with contextlib.ExitStack() as stack:

        def start(handler, requests: list[httpx.Request]) -> None:
            def record(request: httpx.Request) -> httpx.Response:
                requests.append(request)
                return handler(request)

            url = stack.enter_context(running_mcp_server(monkeypatch, httpx.MockTransport(record)))
            monkeypatch.setenv("MCP_SERVER_URL", url)

        yield start


def test_found_ticket_is_read_through_the_mcp_server(mcp_server, agent_token):
    requests: list[httpx.Request] = []
    mcp_server(lambda request: httpx.Response(200, json=INCIDENT), requests)

    lookup = get_ticket(TicketQuery(ticket_id=482))

    assert lookup.outcome == "found"
    assert lookup.ticket.status == "in_progress" and lookup.ticket.branch == "zaragoza_office"
    assert "reported_by" not in lookup.ticket.model_dump()
    # La única llamada al gestor la hace el servidor MCP, con su lectura de ciclo de vida.
    (request,) = requests
    assert (request.method, request.url.path) == ("GET", "/api/incidents/482")
    assert agent_token == [["incidents:read"]]


def test_agent_loads_only_the_read_tool_from_the_server(mcp_server, agent_token):
    mcp_server(lambda request: httpx.Response(200, json=INCIDENT), [])

    tool = asyncio.run(incidents.load_ticket_tool())

    assert tool.name == "get_ticket_status"
    assert "Solo lectura" in tool.description


def test_unknown_ticket_is_not_found(mcp_server, agent_token):
    mcp_server(lambda request: httpx.Response(404, json={"detail": "Incidencia no encontrada."}), [])

    lookup = get_ticket(TicketQuery(ticket_id=482))

    assert lookup.outcome == "not_found" and lookup.ticket is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"detail": "Credenciales no válidas"}),
        httpx.Response(500, json={"detail": "Error interno"}),
        httpx.Response(200, json={"id": 482, "status": "lost"}),
    ],
)
def test_manager_failures_behind_the_server_become_unavailable(mcp_server, agent_token, response):
    mcp_server(lambda request: response, [])

    lookup = get_ticket(TicketQuery(ticket_id=482))

    assert lookup.outcome == "unavailable" and lookup.ticket is None


def test_mcp_server_down_is_unavailable(monkeypatch, agent_token):
    monkeypatch.setenv("MCP_SERVER_URL", "http://127.0.0.1:9/mcp")

    assert get_ticket(TicketQuery(ticket_id=482)).outcome == "unavailable"


def test_slow_mcp_server_is_a_timeout(mcp_server, agent_token, monkeypatch):
    monkeypatch.setattr(incidents, "INCIDENTS_TIMEOUT_SECONDS", 0.3)

    def slow(request):
        time.sleep(1)
        return httpx.Response(200, json=INCIDENT)

    mcp_server(slow, [])

    assert get_ticket(TicketQuery(ticket_id=482)).outcome in {"timeout", "unavailable"}


def test_a_token_without_the_read_scope_is_refused_by_the_server(mcp_server, monkeypatch):
    async def wrong_scope():
        return issue_token(["inventory:read"], client_id="support-agent")

    monkeypatch.setattr(incidents, "fetch_access_token", wrong_scope)
    requests: list[httpx.Request] = []
    mcp_server(lambda request: httpx.Response(200, json=INCIDENT), requests)

    assert get_ticket(TicketQuery(ticket_id=482)).outcome == "unavailable"
    assert requests == []


def test_without_oauth_credentials_the_tool_does_not_call_the_server(monkeypatch):
    for variable in ("MCP_OAUTH_ISSUER", "AGENT_OAUTH_CLIENT_ID", "KEYCLOAK_AGENT_CLIENT_SECRET"):
        monkeypatch.delenv(variable, raising=False)

    assert get_ticket(TicketQuery(ticket_id=482)).outcome == "unavailable"


@pytest.mark.parametrize("payload", [{"ticket_id": 0}, {"ticket_id": -3}, {"ticket_id": 482, "status": "resolved"}])
def test_input_contract_rejects_invalid_or_write_like_queries(payload):
    with pytest.raises(ValidationError):
        TicketQuery(**payload)


def test_fragment_gives_the_model_the_live_status_and_its_source(mcp_server, agent_token):
    mcp_server(lambda request: httpx.Response(200, json=INCIDENT), [])
    lookup = get_ticket(TicketQuery(ticket_id=482))

    fragment = incidents.ticket_fragment(lookup.ticket)

    assert fragment["section"] == "Gestor de incidencias › Ticket 482"
    assert "Estado: en curso (in_progress)" in fragment["text"]
    assert "ana@trackflow.com" not in fragment["text"]
