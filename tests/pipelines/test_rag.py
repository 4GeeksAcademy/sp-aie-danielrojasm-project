"""RAG comercial: `retrieve()`, `generate_answer()`/`query()`, chunking y `setup()`.

Sin servicios reales: Qdrant en modo memoria (`QdrantClient(":memory:")`), embeddings falsos y un
cliente LLM falso. Las similitudes coseno de los vectores 2D se conocen de antemano.
"""

import math
from types import SimpleNamespace

import openai
import pytest
from httpx import Headers
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import Distance, PointStruct, VectorParams

from data.pipelines import rag as pipeline
from data.process import rag as process


QUERY_VECTOR = [1.0, 0.0]


def unit(angle_degrees: float) -> list[float]:
    """Vector unitario cuya similitud coseno con QUERY_VECTOR es cos(ángulo)."""
    radians = math.radians(angle_degrees)
    return [math.cos(radians), math.sin(radians)]


def payload(document: str, index: int, text: str) -> dict:
    return {
        "company": "trackflow",
        "source_document": document,
        "section": f"Sección {index}",
        "language": "es",
        "chunk_index": index,
        "text": text,
    }


@pytest.fixture
def rag_env(monkeypatch):
    monkeypatch.setenv("LLM_API_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setenv("LLM_GENERATION_MODEL", "chat-model")


@pytest.fixture
def memory_qdrant(monkeypatch):
    """Colección `trackflow_knowledge` en memoria con scores 0.95, 0.70, 0.30 y 0.0 para QUERY_VECTOR."""
    client = QdrantClient(":memory:")
    client.create_collection(
        process.COLLECTION_NAME, vectors_config=VectorParams(size=2, distance=Distance.COSINE)
    )
    points = [
        (math.degrees(math.acos(0.95)), payload("returns-policy", 1, "Ventana de 30 días.")),
        (math.degrees(math.acos(0.70)), payload("sla-delivery", 2, "Sin SLA en Black Friday.")),
        (math.degrees(math.acos(0.30)), payload("storage-pricing", 0, "18 USD por metro cúbico.")),
        (90.0, payload("carrier-coverage", 1, "SEUR en Aragón rural.")),
    ]
    client.upsert(
        process.COLLECTION_NAME,
        points=[PointStruct(id=i, vector=unit(angle), payload=data) for i, (angle, data) in enumerate(points)],
    )
    monkeypatch.setattr(pipeline, "get_qdrant_client", lambda: client)
    monkeypatch.setattr(pipeline, "embed", lambda text: QUERY_VECTOR)
    return client


class FakeChat:
    """Cliente LLM falso: registra las llamadas y devuelve un texto fijo."""

    def __init__(self, content: str | None = "Respuesta del modelo", error: Exception | None = None):
        self.calls: list[dict] = []
        self._content = content
        self._error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


# --- retrieve() --------------------------------------------------------------------------------


def test_retrieve_excludes_results_below_min_score(memory_qdrant):
    results = pipeline.retrieve("¿Cuál es la ventana de devolución?", k=5, min_score=0.5)

    assert [r["source_document"] for r in results] == ["returns-policy", "sla-delivery"]


def test_retrieve_can_return_fewer_than_k(memory_qdrant):
    results = pipeline.retrieve("pregunta", k=4, min_score=0.9)

    assert len(results) == 1 < 4


def test_retrieve_returns_empty_list_when_nothing_clears_the_threshold(memory_qdrant):
    assert pipeline.retrieve("¿Capital de Francia?", k=5, min_score=0.99) == []


def test_retrieve_respects_k_before_filtering(memory_qdrant):
    results = pipeline.retrieve("pregunta", k=2, min_score=0.0)

    assert [r["chunk_index"] for r in results] == [1, 2]


def test_retrieve_returns_plain_payload_dicts_not_sdk_objects(memory_qdrant):
    (result,) = pipeline.retrieve("pregunta", k=1, min_score=0.5)

    assert type(result) is dict
    assert set(result) == {"company", "source_document", "section", "language", "chunk_index", "text"}
    assert "score" not in result


def test_retrieve_embeds_the_question_once(memory_qdrant, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(pipeline, "embed", lambda text: seen.append(text) or QUERY_VECTOR)

    pipeline.retrieve("¿Ventana de devolución?", k=3, min_score=0.5)

    assert seen == ["¿Ventana de devolución?"]


def test_retrieve_reports_a_missing_collection_as_service_error(monkeypatch):
    def query_points(**kwargs):
        # Lo que responde un Qdrant real cuando aún no se ha ejecutado setup().
        raise UnexpectedResponse(status_code=404, reason_phrase="Not Found", content=b"", headers=Headers())

    monkeypatch.setattr(pipeline, "get_qdrant_client", lambda: SimpleNamespace(query_points=query_points))
    monkeypatch.setattr(pipeline, "embed", lambda text: QUERY_VECTOR)

    with pytest.raises(process.RagServiceError, match="no está indexada"):
        pipeline.retrieve("pregunta", k=3, min_score=0.5)


# --- generate_answer() y query() ---------------------------------------------------------------


def test_query_returns_the_model_output(rag_env, monkeypatch):
    chunks = [payload("returns-policy", 1, "Ventana de devolución estándar: 30 días desde la entrega.")]
    fake = FakeChat("En TrackFlow la ventana es de 30 días.\nFuente: Sección 1")
    monkeypatch.setattr(pipeline, "retrieve", lambda question: chunks)
    monkeypatch.setattr(pipeline, "get_llm_client", lambda: fake)

    answer = pipeline.query("¿Cuál es la ventana de devolución estándar?")

    assert answer == "En TrackFlow la ventana es de 30 días.\nFuente: Sección 1"


def test_query_never_returns_raw_chunk_text(rag_env, monkeypatch):
    chunk_text = "Ventana de devolución estándar: 30 días desde la entrega."
    fake = FakeChat("Respuesta redactada por el modelo")
    monkeypatch.setattr(pipeline, "retrieve", lambda question: [payload("returns-policy", 1, chunk_text)])
    monkeypatch.setattr(pipeline, "get_llm_client", lambda: fake)

    answer = pipeline.query("¿Ventana de devolución?")

    assert chunk_text not in answer
    # El chunk llega al modelo como contexto, no al consumidor.
    (call,) = fake.calls
    assert chunk_text in call["messages"][-1]["content"]


def test_query_is_retrieve_plus_generate_answer(monkeypatch):
    calls: list[tuple] = []
    context = [payload("sla-delivery", 2, "Sin SLA en Black Friday.")]
    monkeypatch.setattr(pipeline, "retrieve", lambda question: calls.append(("retrieve", question)) or context)
    monkeypatch.setattr(
        pipeline,
        "generate_answer",
        lambda question, ctx: calls.append(("generate", question, ctx)) or "respuesta",
    )

    assert pipeline.query("¿SLA en Black Friday?") == "respuesta"
    assert calls == [("retrieve", "¿SLA en Black Friday?"), ("generate", "¿SLA en Black Friday?", context)]


def test_generate_answer_uses_the_generation_model_with_the_sales_voice(rag_env, monkeypatch):
    fake = FakeChat()
    monkeypatch.setattr(pipeline, "get_llm_client", lambda: fake)

    pipeline.generate_answer("¿Ventana de devolución?", [payload("returns-policy", 1, "30 días.")])

    (call,) = fake.calls
    assert call["model"] == "chat-model"
    system = call["messages"][0]["content"]
    assert "vendedor de TrackFlow" in system
    assert "Miguel Torres" in system
    assert "Black Friday" in system
    assert "Sección 1" in call["messages"][1]["content"]


def test_query_without_context_still_asks_the_model_to_admit_it(rag_env, monkeypatch):
    fake = FakeChat("La base de conocimiento no tiene información suficiente sobre eso.")
    monkeypatch.setattr(pipeline, "retrieve", lambda question: [])
    monkeypatch.setattr(pipeline, "get_llm_client", lambda: fake)

    answer = pipeline.query("¿Cuál es la capital de Francia?")

    assert answer == "La base de conocimiento no tiene información suficiente sobre eso."
    (call,) = fake.calls
    assert pipeline.NO_CONTEXT in call["messages"][-1]["content"]


def test_query_rejects_an_empty_question():
    with pytest.raises(ValueError):
        pipeline.query("   ")


def test_generation_failure_is_a_service_error(rag_env, monkeypatch):
    error = openai.APIConnectionError(request=SimpleNamespace(method="POST", url="http://llm.test"))
    monkeypatch.setattr(pipeline, "get_llm_client", lambda: FakeChat(error=error))

    with pytest.raises(process.RagServiceError):
        pipeline.generate_answer("pregunta", [])


def test_empty_model_output_is_a_service_error(rag_env, monkeypatch):
    monkeypatch.setattr(pipeline, "get_llm_client", lambda: FakeChat(content="  "))

    with pytest.raises(process.RagServiceError):
        pipeline.generate_answer("pregunta", [])


# --- Configuración -------------------------------------------------------------------------------


def test_settings_reject_the_same_model_for_embeddings_and_generation(rag_env, monkeypatch):
    monkeypatch.setenv("LLM_GENERATION_MODEL", "embedding-model")

    with pytest.raises(process.RagConfigurationError):
        process.load_settings()


def test_settings_report_missing_variables(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(process.RagConfigurationError, match="LLM_API_KEY"):
        process.load_settings()


# --- Chunking y setup() ----------------------------------------------------------------------


def test_every_source_document_produces_at_least_three_chunks():
    chunks = process.load_chunks()
    by_document: dict[str, int] = {}
    for chunk in chunks:
        by_document[chunk.source_document] = by_document.get(chunk.source_document, 0) + 1

    assert by_document.keys() == {"sla-delivery", "returns-policy", "carrier-coverage", "storage-pricing"}
    assert min(by_document.values()) >= 3


def test_chunks_carry_the_context_payload_fields():
    for chunk in process.load_chunks():
        data = chunk.payload()
        assert data["company"] == "trackflow"
        assert data["language"] == "es"
        assert data["section"]
        assert data["text"].strip()
        assert set(data) == {"company", "source_document", "section", "language", "chunk_index", "text"}


def test_chunking_keeps_lists_with_their_lead_in_and_never_cuts_a_sentence():
    markdown = """# Política

El proceso funciona así:

1. Paso uno.
2. Paso dos,
   que sigue en otra línea.

Ventana estándar: 30 días desde la entrega, salvo contrato.
"""
    chunks = process.parse_document(markdown, source_document="returns-policy", language="es")

    assert [c.text for c in chunks] == [
        "El proceso funciona así:\n1. Paso uno.\n2. Paso dos, que sigue en otra línea.",
        "Ventana estándar: 30 días desde la entrega, salvo contrato.",
    ]
    assert [c.section for c in chunks] == ["Política › El proceso funciona así", "Política › Ventana estándar"]
    assert all(c.text.rstrip().endswith((".", ":")) for c in chunks)


def test_chunking_follows_markdown_headings():
    markdown = "# Tarifas\n\n## Los Ángeles\n\n18 USD por metro cúbico.\n\n## Zaragoza\n\n16 EUR por metro cúbico.\n"
    chunks = process.parse_document(markdown, source_document="storage-pricing", language="es")

    assert [(c.section, c.chunk_index) for c in chunks] == [
        ("Tarifas › Los Ángeles", 0),
        ("Tarifas › Zaragoza", 1),
    ]


def test_point_ids_are_deterministic():
    first = [c.point_id for c in process.load_chunks()]
    second = [c.point_id for c in process.load_chunks()]

    assert first == second
    assert len(set(first)) == len(first)


def test_setup_is_idempotent(monkeypatch):
    client = QdrantClient(":memory:")
    monkeypatch.setattr(process, "embed", lambda text: [1.0, float(len(text) % 7), 0.5])

    first = process.setup(client=client)
    second = process.setup(client=client)

    assert first == second == len(process.load_chunks())
    assert client.count(process.COLLECTION_NAME).count == first
    point = client.retrieve(process.COLLECTION_NAME, ids=[process.load_chunks()[0].point_id])[0]
    assert point.payload["source_document"] == "carrier-coverage"


def test_embed_normalizes_text_and_uses_the_embedding_model(rag_env, monkeypatch):
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])

    monkeypatch.setattr(
        process, "get_llm_client", lambda: SimpleNamespace(embeddings=SimpleNamespace(create=create))
    )

    assert process.embed("  Ventana\n de   devolución ") == [0.1, 0.2]
    assert calls == [{"model": "embedding-model", "input": "Ventana de devolución"}]
