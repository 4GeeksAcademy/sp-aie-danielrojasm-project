"""Enrutador del agente (`plan_route`): decide el modelo, con salvaguardas y reglas de respaldo."""

from types import SimpleNamespace

import openai
import pytest

from services.support_agent import routing


class FakeRouterModel:
    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.calls: list[dict] = []
        self._content = content
        self._error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))])


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setenv("LLM_API_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setenv("LLM_GENERATION_MODEL", "chat-model")

    def use(**kwargs) -> FakeRouterModel:
        fake = FakeRouterModel(**kwargs)
        monkeypatch.setattr(routing, "get_llm_client", lambda: fake)
        return fake

    return use


@pytest.mark.parametrize(
    ("content", "ticket_ids", "needs_knowledge"),
    [
        ('{"ticket_ids": [482], "needs_knowledge": false}', [482], False),
        ('{"ticket_ids": [], "needs_knowledge": true}', [], True),
        ('{"ticket_ids": [482], "needs_knowledge": true}', [482], True),
    ],
)
def test_model_decides_the_sources(model, content, ticket_ids, needs_knowledge):
    fake = model(content=content)

    plan = routing.plan_route("¿En qué estado está el ticket 482 y cuál es la ventana de devolución?")

    assert (plan.ticket_ids, plan.needs_knowledge, plan.decided_by) == (ticket_ids, needs_knowledge, "llm")
    (call,) = fake.calls
    assert call["model"] == "chat-model" and call["temperature"] == 0
    assert call["response_format"] == {"type": "json_object"}


def test_ticket_ids_not_written_in_the_question_are_discarded(model):
    model(content='{"ticket_ids": [482, 999], "needs_knowledge": false}')

    plan = routing.plan_route("¿Cómo va el ticket 482?")

    assert plan.ticket_ids == [482]


def test_without_tickets_the_question_goes_to_the_knowledge_base(model):
    model(content='{"ticket_ids": [], "needs_knowledge": false}')

    assert routing.plan_route("Hola").needs_knowledge is True


@pytest.mark.parametrize(
    "fake",
    [
        {"error": openai.APIConnectionError(request=SimpleNamespace(method="POST", url="http://llm.test"))},
        {"content": "no es json"},
        {"content": '{"needs_knowledge": "quizá"}'},
    ],
)
def test_model_failure_falls_back_to_rules(model, fake):
    model(**fake)

    plan = routing.plan_route("¿En qué estado está el ticket #482?")

    assert (plan.ticket_ids, plan.needs_knowledge, plan.decided_by) == ([482], False, "rules")


def test_missing_llm_configuration_falls_back_to_rules(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    assert routing.plan_route("¿Ventana de devolución?").decided_by == "rules"


@pytest.mark.parametrize(
    ("question", "ticket_ids", "needs_knowledge"),
    [
        ("¿En qué estado está el ticket 482?", [482], False),
        ("Estado de la incidencia nº 17 y del caso #18", [17, 18], False),
        ("¿Cuál es la ventana de devolución de 30 días?", [], True),
        ("¿Cuánto cuesta almacenar 50 metros cúbicos?", [], True),
    ],
)
def test_rules_only_take_explicit_ticket_references(question, ticket_ids, needs_knowledge):
    plan = routing.route_by_rules(question)

    assert (plan.ticket_ids, plan.needs_knowledge) == (ticket_ids, needs_knowledge)
