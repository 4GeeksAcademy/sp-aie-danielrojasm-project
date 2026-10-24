"""Streaming de tokens del agente (`streaming.py`) y abort de la corrida (`runner.run_agent(on_token, abort)`)."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from data.pipelines import rag
from services.support_agent import nodes, streaming
from services.support_agent.memory import self_evaluation
from services.support_agent.routing import route_by_rules
from services.support_agent.runner import run_agent
from services.support_agent.streaming import GenerationAborted, JsonFieldStreamer
from services.support_agent.tracing import load_trace, trace_path


ANSWER = "Son 30 días \"naturales\".\nFuente: Ventana 😀"
CHUNK = {"source_document": "returns-policy", "section": "Ventana", "chunk_index": 1, "text": "30 días."}


def feed_in_pieces(text: str, size: int, key: str = "respuesta") -> str:
    streamer = JsonFieldStreamer(key)
    return "".join(streamer.feed(text[index : index + size]) for index in range(0, len(text), size))


@pytest.mark.parametrize("size", [1, 2, 3, 7, 1000])
def test_json_field_streamer_decodes_the_value_whatever_the_chunk_size(size):
    body = json.dumps({"respuesta": ANSWER, "propuesta_memoria": {"hecho": "no se muestra"}})

    assert feed_in_pieces(body, size) == ANSWER


def test_json_field_streamer_ignores_other_keys_and_non_text_values():
    body = json.dumps({"propuesta_memoria": {"nota": "respuesta"}, "respuesta": "Hola"})

    assert feed_in_pieces(body, 2) == "Hola"
    assert feed_in_pieces(json.dumps({"respuesta": None}), 3) == ""


class Stream:
    """Trozos a ritmo de modelo: el nodo genera en otro hilo y el abort llega mientras sigue generando."""

    def __init__(self, parts: list[str]):
        self.parts = parts
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for part in self.parts:
            time.sleep(0.01)
            self.consumed += 1
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=part))])

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_model(monkeypatch):
    body = json.dumps({"respuesta": "Son 30 días naturales desde la entrega.\nFuente: Ventana"})
    calls: list[dict] = []

    def create(**request):
        calls.append(request)
        if request.get("stream"):
            stream = Stream([body[index : index + 3] for index in range(0, len(body), 3)])
            calls[-1]["response"] = stream
            return stream
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=body))])

    monkeypatch.setattr(nodes, "plan_route", route_by_rules)
    monkeypatch.setattr(rag, "retrieve", lambda question: [CHUNK])
    monkeypatch.setattr(self_evaluation, "load_settings", lambda: SimpleNamespace(generation_model="fake-model"))
    monkeypatch.setattr(
        self_evaluation, "get_llm_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    )
    return calls


def test_without_on_token_the_model_call_is_not_streamed(fake_model):
    run = run_agent("¿Cuál es la ventana de devolución?")

    assert "stream" not in fake_model[0]
    assert run.state["answer"].startswith("Son 30 días naturales")


def test_on_token_receives_only_the_visible_answer(fake_model):
    tokens: list[str] = []

    run = run_agent("¿Cuál es la ventana de devolución?", on_token=tokens.append)

    assert len(tokens) > 5
    assert "".join(tokens) == "Son 30 días naturales desde la entrega.\nFuente: Ventana"
    assert run.state["answer"].startswith("Son 30 días naturales")
    assert fake_model[0]["response"].closed


def test_abort_stops_the_model_stream_and_marks_the_trace_interrupted(fake_model):
    abort = threading.Event()
    tokens: list[str] = []

    def on_token(token: str) -> None:
        tokens.append(token)
        if len(tokens) == 2:
            abort.set()

    with pytest.raises(GenerationAborted):
        run_agent("¿Cuál es la ventana de devolución?", on_token=on_token, abort=abort, run_id="run-abortada")

    stream = fake_model[0]["response"]
    assert len(tokens) == 2
    assert stream.closed and stream.consumed < len(stream.parts)
    trace = load_trace(trace_path("run-abortada"))
    assert trace["status"] == "interrupted"
    assert trace["steps"][-1]["node"] != nodes.GENERATE_ANSWER


def test_an_abort_before_the_model_call_skips_it(fake_model):
    abort = threading.Event()
    abort.set()

    with pytest.raises(GenerationAborted):
        run_agent("¿Cuál es la ventana de devolución?", on_token=lambda token: None, abort=abort)

    assert fake_model == []


def test_complete_outside_a_graph_is_a_plain_call():
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **request: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
            )
        )
    )

    assert streaming.current_stream() is None
    assert streaming.complete(client, model="m", messages=[]) == "ok"
