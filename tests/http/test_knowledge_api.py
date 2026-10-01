"""`POST /knowledge/query`: delega en `query()` y solo devuelve `answer`."""

import pytest
from fastapi.testclient import TestClient

from data.process.rag import RagConfigurationError, RagServiceError
from services.api.main import app
from services.api.routes import knowledge


PASSWORD = "correct-password"


@pytest.fixture
def auth_client():
    with TestClient(app) as client:
        client.post("/users", json={"email": "ana@example.com", "password": PASSWORD, "name": "Ana"})
        token = client.post(
            "/auth/login", json={"email": "ana@example.com", "password": PASSWORD}
        ).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


def test_requires_a_session():
    with TestClient(app) as client:
        response = client.post("/knowledge/query", json={"question": "¿Ventana de devolución?"})

    assert response.status_code == 401


def test_returns_only_the_generated_answer(auth_client, monkeypatch):
    questions: list[str] = []
    monkeypatch.setattr(knowledge, "query", lambda question: questions.append(question) or "Son 30 días.")

    response = auth_client.post("/knowledge/query", json={"question": "  ¿Ventana de devolución?  "})

    assert response.status_code == 200
    assert response.json() == {"answer": "Son 30 días."}
    assert questions == ["¿Ventana de devolución?"]


@pytest.mark.parametrize("error", [RagServiceError("Qdrant caído"), RagConfigurationError("Falta LLM_API_KEY")])
def test_unavailable_dependencies_return_503_without_internal_details(auth_client, monkeypatch, error):
    def fail(question):
        raise error

    monkeypatch.setattr(knowledge, "query", fail)

    response = auth_client.post("/knowledge/query", json={"question": "¿Ventana de devolución?"})

    assert response.status_code == 503
    assert response.json() == {"detail": knowledge.KNOWLEDGE_UNAVAILABLE_DETAIL}
    assert "Qdrant" not in response.text and "LLM_API_KEY" not in response.text


@pytest.mark.parametrize(
    "body",
    [{"question": "  "}, {"question": "x" * 1001}, {"question": "¿Ventana?", "k": 10}, {}],
)
def test_rejects_invalid_questions(auth_client, monkeypatch, body):
    monkeypatch.setattr(knowledge, "query", lambda question: pytest.fail("no debe llamar al RAG"))

    assert auth_client.post("/knowledge/query", json=body).status_code == 422
