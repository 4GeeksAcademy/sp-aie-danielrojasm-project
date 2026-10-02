"""Tool `get_ticket`: contrato, auth de la cuenta de servicio, solo lectura, timeout y fallback.

Las respuestas del gestor llegan por `httpx.MockTransport`, que además registra cada petición.
"""

import httpx
import pytest
from jose import jwt
from pydantic import ValidationError

from services.api.security import ALGORITHM
from services.support_agent.tools import incidents
from services.support_agent.tools.incidents import TicketQuery, get_ticket
from tests.helpers import TEST_SECRET


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


@pytest.fixture(autouse=True)
def service_account(monkeypatch):
    monkeypatch.setenv("AGENT_SERVICE_USER_ID", "service-user-id")
    monkeypatch.setenv("INCIDENTS_API_URL", "http://incidents.test/")


def client_answering(handler, requests: list[httpx.Request]) -> httpx.Client:
    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(record))


def test_found_ticket_is_read_with_a_single_authenticated_get():
    requests: list[httpx.Request] = []
    client = client_answering(lambda request: httpx.Response(200, json=INCIDENT), requests)

    lookup = get_ticket(TicketQuery(ticket_id=482), client=client)

    assert lookup.outcome == "found"
    assert lookup.ticket.status == "in_progress" and lookup.ticket.branch == "zaragoza_office"
    assert "reported_by" not in lookup.ticket.model_dump()
    (request,) = requests
    assert (request.method, str(request.url)) == ("GET", "http://incidents.test/api/incidents/482")
    token = request.headers["Authorization"].removeprefix("Bearer ")
    assert jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])["sub"] == "service-user-id"


def test_timeout_is_numeric_and_applied_to_the_request():
    requests: list[httpx.Request] = []
    client = client_answering(lambda request: httpx.Response(200, json=INCIDENT), requests)

    get_ticket(TicketQuery(ticket_id=482), client=client)

    assert 3 <= incidents.INCIDENTS_TIMEOUT_SECONDS <= 5
    timeouts = requests[0].extensions["timeout"]
    assert timeouts == {key: incidents.INCIDENTS_TIMEOUT_SECONDS for key in ("connect", "read", "write", "pool")}


@pytest.mark.parametrize(
    ("response", "outcome"),
    [
        (httpx.Response(404, json={"detail": "Incidencia no encontrada."}), "not_found"),
        (httpx.Response(401, json={"detail": "Credenciales no válidas"}), "unavailable"),
        (httpx.Response(500, json={"detail": "Error interno"}), "unavailable"),
        (httpx.Response(200, text="<html>"), "unavailable"),
        (httpx.Response(200, json={"id": 482, "status": "lost"}), "unavailable"),
    ],
)
def test_service_answers_that_are_not_a_ticket_become_a_fallback_outcome(response, outcome):
    lookup = get_ticket(TicketQuery(ticket_id=482), client=client_answering(lambda request: response, []))

    assert lookup.outcome == outcome
    assert lookup.ticket is None


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (httpx.ReadTimeout("lenta"), "timeout"),
        (httpx.ConnectTimeout("lenta"), "timeout"),
        (httpx.ConnectError("caída"), "unavailable"),
    ],
)
def test_network_failures_become_a_fallback_outcome(error, outcome):
    def fail(request):
        raise error

    lookup = get_ticket(TicketQuery(ticket_id=482), client=client_answering(fail, []))

    assert lookup.outcome == outcome


def test_real_timeout_does_not_hang(monkeypatch):
    # 10.255.255.1 no responde: la conexión agota el timeout en lugar de quedarse colgada.
    monkeypatch.setattr(incidents, "INCIDENTS_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setenv("INCIDENTS_API_URL", "http://10.255.255.1:81")

    assert get_ticket(TicketQuery(ticket_id=482)).outcome in {"timeout", "unavailable"}


def test_without_service_credentials_the_tool_does_not_call_the_service(monkeypatch):
    monkeypatch.delenv("AGENT_SERVICE_USER_ID")
    requests: list[httpx.Request] = []

    lookup = get_ticket(TicketQuery(ticket_id=482), client=client_answering(lambda request: httpx.Response(200), requests))

    assert lookup.outcome == "unavailable"
    assert requests == []


@pytest.mark.parametrize("payload", [{"ticket_id": 0}, {"ticket_id": -3}, {"ticket_id": 482, "status": "resolved"}])
def test_input_contract_rejects_invalid_or_write_like_queries(payload):
    with pytest.raises(ValidationError):
        TicketQuery(**payload)


def test_fragment_gives_the_model_the_live_status_and_its_source():
    lookup = get_ticket(
        TicketQuery(ticket_id=482), client=client_answering(lambda request: httpx.Response(200, json=INCIDENT), [])
    )

    fragment = incidents.ticket_fragment(lookup.ticket)

    assert fragment["section"] == "Gestor de incidencias › Ticket 482"
    assert "Estado: en curso (in_progress)" in fragment["text"]
    assert "ana@trackflow.com" not in fragment["text"]
