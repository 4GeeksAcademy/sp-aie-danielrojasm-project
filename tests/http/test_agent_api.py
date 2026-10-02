"""`POST /agent/query`: invoca el grafo y traduce su resultado sin exponer detalles internos.

El enrutado usa las reglas (`route_by_rules`) para no depender del modelo. El caso de tickets es de extremo a extremo:
la tool lee la incidencia con `GET /api/incidents/{id}` de esta misma API (TinyDB temporal del test).
"""

from functools import partial

import pytest
from fastapi.testclient import TestClient

from data.pipelines import rag
from data.process.rag import RagConfigurationError, RagServiceError
from services.api.main import app
from services.support_agent import nodes, router
from services.support_agent.routing import route_by_rules
from services.support_agent.tools.incidents import get_ticket
from services.support_agent.tracing import load_trace, trace_path


PASSWORD = "correct-password"
CHUNK = {"source_document": "returns-policy", "section": "Ventana", "chunk_index": 1, "text": "30 días."}


@pytest.fixture(autouse=True)
def rules_router(monkeypatch):
    monkeypatch.setattr(nodes, "plan_route", route_by_rules)


@pytest.fixture
def auth_client():
    with TestClient(app) as client:
        user = client.post("/users", json={"email": "ana@example.com", "password": PASSWORD, "name": "Ana"}).json()
        client.user_id = user["id"]
        token = client.post(
            "/auth/login", json={"email": "ana@example.com", "password": PASSWORD}
        ).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


@pytest.fixture
def fake_rag(monkeypatch):
    monkeypatch.setattr(rag, "retrieve", lambda question: [CHUNK])
    monkeypatch.setattr(rag, "generate_answer", lambda question, context: "Son 30 días.")


def test_requires_a_session():
    with TestClient(app) as client:
        response = client.post("/agent/query", json={"question": "¿Ventana de devolución?"})

    assert response.status_code == 401


def test_returns_the_graph_answer_and_the_run_reference(auth_client, fake_rag):
    response = auth_client.post("/agent/query", json={"question": "¿Ventana de devolución?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Son 30 días."
    assert trace_path(body["run_id"]).exists()


# TestClient ignora el timeout de la tool (no hay red); su efecto se prueba en test_incidents_tool.py.
@pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument with the TestClient")
def test_ticket_question_reads_the_live_incident_manager(auth_client, monkeypatch):
    incident = auth_client.post(
        "/api/incidents",
        json={
            "title": "Paquete perdido en Zaragoza",
            "description": "El cliente no recibió el pedido.",
            "category": "lost_parcel",
            "origin": "customer",
            "branch": "zaragoza_office",
        },
    ).json()
    auth_client.patch(f"/api/incidents/{incident['id']}/status", json={"status": "in_progress"})
    monkeypatch.setenv("INCIDENTS_API_URL", str(auth_client.base_url))
    monkeypatch.setenv("AGENT_SERVICE_USER_ID", auth_client.user_id)
    monkeypatch.setattr(nodes, "get_ticket", partial(get_ticket, client=auth_client))
    monkeypatch.setattr(rag, "retrieve", lambda question: pytest.fail("una pregunta de ticket no usa el RAG"))
    contexts: list = []
    monkeypatch.setattr(rag, "generate_answer", lambda question, context: contexts.append(context) or "En curso.")

    response = auth_client.post("/agent/query", json={"question": f"¿En qué estado está el ticket {incident['id']}?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "En curso."
    ((fragment,),) = contexts
    assert "Estado: en curso (in_progress)" in fragment["text"]
    trace = load_trace(trace_path(response.json()["run_id"]))
    assert trace["sources_used"] == ["incidents_tool"]
    (lookup,) = trace["final_state"]["tickets"]
    assert lookup["outcome"] == "found" and lookup["ticket"]["status"] == "in_progress"


def test_ticket_question_with_the_incident_manager_down_answers_honestly(auth_client, monkeypatch):
    monkeypatch.setenv("INCIDENTS_API_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("AGENT_SERVICE_USER_ID", auth_client.user_id)
    monkeypatch.setattr(rag, "generate_answer", lambda question, context: pytest.fail("no debe generar"))

    response = auth_client.post("/agent/query", json={"question": "¿En qué estado está el ticket 482?"})

    assert response.status_code == 200
    assert response.json()["answer"].startswith(nodes.TICKET_UNCONFIRMED.format(ticket_id=482))


def test_empty_question_returns_the_graph_error(auth_client, monkeypatch):
    monkeypatch.setattr(rag, "retrieve", lambda question: pytest.fail("no debe recuperar"))

    response = auth_client.post("/agent/query", json={"question": "   "})

    assert response.status_code == 422
    assert response.json() == {"detail": nodes.EMPTY_QUESTION_ERROR}


@pytest.mark.parametrize("error", [RagServiceError("Qdrant caído"), RagConfigurationError("Falta LLM_API_KEY")])
def test_unavailable_dependencies_return_503_without_internal_details(auth_client, monkeypatch, error):
    def fail(question):
        raise error

    monkeypatch.setattr(rag, "retrieve", fail)

    response = auth_client.post("/agent/query", json={"question": "¿Ventana de devolución?"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail.startswith("El agente de soporte no está disponible")
    assert "Qdrant" not in response.text and "LLM_API_KEY" not in response.text


def test_unexpected_node_failure_returns_a_clear_500_without_stack_trace(auth_client, fake_rag, monkeypatch):
    def broken(question, context):
        raise KeyError("text")

    monkeypatch.setattr(rag, "generate_answer", broken)

    response = auth_client.post("/agent/query", json={"question": "¿Ventana de devolución?"})

    assert response.status_code == 500
    detail = response.json()["detail"]
    run_id = detail.rsplit(" ", 1)[-1].rstrip(".")
    assert detail == router.AGENT_FAILED_DETAIL.format(run_id=run_id)
    assert "KeyError" not in response.text and "Traceback" not in response.text
    assert trace_path(run_id).exists()


@pytest.mark.parametrize("body", [{"question": "x" * 1001}, {"question": "¿Ventana?", "k": 10}, {}])
def test_rejects_invalid_bodies(auth_client, monkeypatch, body):
    monkeypatch.setattr(rag, "retrieve", lambda question: pytest.fail("no debe invocar el grafo"))

    assert auth_client.post("/agent/query", json=body).status_code == 422
