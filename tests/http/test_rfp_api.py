"""`/rfps/*`: la subida crea el ticket, guarda el PDF y encola el análisis sin ejecutarlo en la API."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError as BrokerError

from data.pipelines.rfp_intake import compliance, generators, llm, response_runner, runner
from services.api import database as api_database
from services.api.main import app
from services.rfp_intake import router as rfp_router
from tests.pipelines.test_rfp_intake_flow import AGENT_OUTPUTS, RFP_LINES, minimal_pdf
from tests.pipelines.test_rfp_response_agents import reverse_draft


PASSWORD = "correct-password"


@pytest.fixture
def queued(monkeypatch):
    """Sustituye el encolado: guarda los `ticket_id` en lugar de publicarlos en Redis."""
    tickets: list[str] = []

    def apply_async(args, retry):
        tickets.append(args[0])
        return SimpleNamespace(id="task-123")

    monkeypatch.setattr(rfp_router.process_rfp_ticket_task, "apply_async", apply_async)
    return tickets


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'trackflow.db').as_posix()}")
    monkeypatch.setenv("RFP_RAW_DIR", str(tmp_path / "raw"))
    api_database.get_engine.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    api_database.get_engine.cache_clear()


@pytest.fixture
def auth_client(client):
    client.post("/users", json={"email": "ana@example.com", "password": PASSWORD, "name": "Ana"})
    token = client.post("/auth/login", json={"email": "ana@example.com", "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def upload(client: TestClient, content: bytes, filename: str = "rfp.pdf"):
    return client.post("/rfps", files={"file": (filename, content, "application/pdf")})


def test_requires_a_session(client):
    assert client.get("/rfps").status_code == 401
    assert upload(client, minimal_pdf(RFP_LINES)).status_code == 401


def test_upload_creates_the_ticket_saves_the_pdf_and_only_enqueues(auth_client, queued, tmp_path):
    response = upload(auth_client, minimal_pdf(RFP_LINES), "luna.pdf")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "analizando" and body["task_id"] == "task-123"
    assert queued == [body["ticket_id"]]
    assert (tmp_path / "raw" / f"{body['ticket_id']}.pdf").read_bytes().startswith(b"%PDF-")

    detail = auth_client.get(f"/rfps/{body['ticket_id']}").json()
    assert detail["status"] == "analizando"
    assert detail["original_filename"] == "luna.pdf"
    assert detail["metadata"] is None and detail["sections"] == [] and detail["handoff_ready"] is False
    listed = auth_client.get("/rfps").json()
    assert [item["ticket_id"] for item in listed] == [body["ticket_id"]]


@pytest.mark.parametrize(
    ("content", "status_code", "detail"),
    [
        (b"", 400, rfp_router.EMPTY_FILE_DETAIL),
        (b"Hola, esto es un .txt renombrado", 400, rfp_router.NOT_A_PDF_DETAIL),
        (b"%PDF-" + b"0" * rfp_router.MAX_UPLOAD_BYTES, 413, rfp_router.TOO_LARGE_DETAIL),
    ],
    ids=["empty", "not-a-pdf", "too-large"],
)
def test_upload_rejects_files_that_are_not_valid_pdfs(auth_client, queued, tmp_path, content, status_code, detail):
    response = upload(auth_client, content)

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert queued == []
    assert auth_client.get("/rfps").json() == []


def test_upload_without_queue_returns_503_and_leaves_no_ticket(auth_client, monkeypatch, tmp_path):
    def broker_down(args, retry):
        raise BrokerError("Error 10061 connecting to 127.0.0.1:6379")

    monkeypatch.setattr(rfp_router.process_rfp_ticket_task, "apply_async", broker_down)

    response = upload(auth_client, minimal_pdf(RFP_LINES))

    assert response.status_code == 503
    assert response.json() == {"detail": rfp_router.QUEUE_UNAVAILABLE_DETAIL}
    assert auth_client.get("/rfps").json() == []
    assert list((tmp_path / "raw").glob("*.pdf")) == []


def test_without_database_the_routes_answer_503(auth_client, monkeypatch, queued):
    monkeypatch.delenv("DATABASE_URL")
    api_database.get_engine.cache_clear()

    assert auth_client.get("/rfps").status_code == 503
    assert upload(auth_client, minimal_pdf(RFP_LINES)).json() == {"detail": rfp_router.RFP_UNAVAILABLE_DETAIL}


def test_unknown_ticket_returns_404(auth_client):
    response = auth_client.get("/rfps/no-existe")

    assert response.status_code == 404
    assert response.json() == {"detail": rfp_router.TICKET_NOT_FOUND_DETAIL}


def test_processed_ticket_shows_what_each_department_has_to_provide(auth_client, queued, monkeypatch):
    def ask_json(agent, system_prompt, user_prompt, schema):
        if agent == "classifier":
            return schema.model_validate({"is_rfp": True, "document_type": "rfp_informal", "confidence": 0.9, "reason": "Pide una propuesta."})
        return schema.model_validate(AGENT_OUTPUTS[agent])

    monkeypatch.setattr(llm, "ask_json", ask_json)
    ticket_id = upload(auth_client, minimal_pdf(RFP_LINES)).json()["ticket_id"]
    # Lo que haría el worker de Celery con el mensaje encolado.
    runner.process_ticket(api_database.get_engine(), queued[0])

    detail = auth_client.get(f"/rfps/{ticket_id}").json()

    assert detail["status"] == "analisis_completo" and detail["handoff_ready"] is True
    assert detail["classification"] == {"is_rfp": True, "confidence": 0.9, "reason": "Pide una propuesta."}
    assert detail["metadata"]["currency"] == "USD" and detail["metadata"]["monthly_volume"] == 5000
    assert detail["metadata"]["readability"]["estimated_tokens"] > 0
    assert "document_markdown" not in detail["metadata"]
    assert [(s["department_id"], s["responsible"]) for s in detail["sections"]] == [
        ("warehouse", "Ana Whitfield"),
        ("lastmile", "Carlos Vega"),
    ]
    assert detail["synthesis"]["next_steps"] == AGENT_OUTPUTS["synthesizer"]["next_steps"]
    listed = auth_client.get("/rfps").json()[0]
    assert listed["client_name"] == "Luna Cosmetics" and listed["departments_needed"] == ["warehouse", "lastmile"]


def test_generated_ticket_shows_each_draft_with_its_evaluation(auth_client, queued, monkeypatch):
    def ask_json(agent, system_prompt, user_prompt, schema):
        if agent == "classifier":
            return schema.model_validate({"is_rfp": True, "document_type": "rfp_informal", "confidence": 0.9, "reason": "Pide una propuesta."})
        if agent in AGENT_OUTPUTS:
            return schema.model_validate(AGENT_OUTPUTS[agent])
        if agent.endswith("_generator"):
            # Moneda equivocada (Luna es de EE. UU.): no pasa compliance y agota el límite.
            return schema.model_validate({"content": reverse_draft()})
        if agent.endswith("_relevance_evaluator"):
            return schema.model_validate({"missing_aspect_ids": []})
        return schema.model_validate({"violations": []})

    monkeypatch.setattr(llm, "ask_json", ask_json)
    monkeypatch.setattr(generators, "retrieve_knowledge", lambda department_id: [])
    ticket_id = upload(auth_client, minimal_pdf(RFP_LINES)).json()["ticket_id"]
    engine = api_database.get_engine()
    runner.process_ticket(engine, queued[0])
    response_runner.generate_responses(engine, ticket_id, max_iterations=1)

    detail = auth_client.get(f"/rfps/{ticket_id}").json()

    assert detail["status"] == "needs_human_review"
    assert detail["response_handoff_ready"] is True and detail["max_iterations"] == 1
    warehouse = detail["sections"][0]
    assert warehouse["draft_status"] == "needs_human_review" and warehouse["iterations"] == 1
    assert warehouse["draft_content"].startswith("## Reverse Logistics")
    evaluation = warehouse["evaluation"]
    assert evaluation["overall_pass"] is False and evaluation["readability"]["pass"] is True
    assert evaluation["compliance"] == {
        "pass": False,
        "rule_ids": ["currency-by-country"],
        "violations": evaluation["compliance"]["violations"],
        "checked_rule_ids": list(compliance.RULES),
    }
    assert "[currency-by-country]" in evaluation["feedback_for_generator"]
    assert auth_client.get("/rfps").json()[0]["status"] == "needs_human_review"
