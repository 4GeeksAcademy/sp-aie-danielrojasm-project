"""Base de conocimiento comercial de TrackFlow (RAG): preparación de datos e indexación.

Dos puntos de entrada, cada uno con una sola responsabilidad:

- `setup()` lee los documentos fuente de `docs/company-knowledge-base/`, los trocea por unidades
  semánticas y los indexa en la colección de Qdrant `trackflow_knowledge` (limpiar y recargar).
- `embed()` convierte un texto en vector con el modelo de embeddings (`LLM_EMBEDDING_MODEL`). Es la
  misma función para los chunks al indexar y para la pregunta al consultar.

La recuperación y la generación viven en `data/pipelines/rag.py`. Diseño en `docs/rag/rag-design.md`.

Uso: `uv run python -m data.process.rag` desde la raíz (lee el `.env` raíz).
"""

from __future__ import annotations

import logging
import os
import re
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import openai
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from qdrant_client.models import Distance, PointStruct, VectorParams


logger = logging.getLogger("trackflow.rag")

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = ROOT / "docs" / "company-knowledge-base"

COMPANY = "trackflow"
COLLECTION_NAME = "trackflow_knowledge"
# `trackflow-<source_document>.<language>.md`, como en `00-general-contexts/trackflow/`.
DOCUMENT_NAME = re.compile(rf"^{COMPANY}-(?P<source_document>[a-z0-9-]+)\.(?P<language>[a-z]{{2}})\.md$")
DISTANCE = Distance.COSINE
# Tope de seguridad: un bloque más largo se parte por líneas y, si hace falta, por frases.
MAX_CHUNK_CHARS = 1200
# Una etiqueta de sección derivada del texto ("Ventana de devolución estándar: ...") no pasa de aquí.
MAX_LABEL_WORDS = 6
MAX_LABEL_CHARS = 80
SECTION_SEPARATOR = " › "
POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, f"https://trackflow.example/{COLLECTION_NAME}")

LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# Primera pausa de una frase: lo anterior suele nombrar el tema del bloque.
CLAUSE_END = re.compile(r"\s*[.,;:(—]")


class RagConfigurationError(RuntimeError):
    """Falta configuración (variables de entorno) para usar el RAG."""


class RagServiceError(RuntimeError):
    """Qdrant o el gateway LLM no respondieron como se esperaba. El mensaje no lleva datos sensibles."""


# --- Configuración y clientes ----------------------------------------------------------------


@dataclass(frozen=True)
class RagSettings:
    llm_api_url: str
    llm_api_key: str
    embedding_model: str
    generation_model: str
    qdrant_url: str


def load_settings() -> RagSettings:
    """Lee la configuración del entorno. Embeddings y generación tienen que ser modelos distintos."""
    values = {
        "LLM_API_URL": os.getenv("LLM_API_URL", "").strip(),
        "LLM_API_KEY": os.getenv("LLM_API_KEY", "").strip(),
        "LLM_EMBEDDING_MODEL": os.getenv("LLM_EMBEDDING_MODEL", "").strip(),
        "LLM_GENERATION_MODEL": os.getenv("LLM_GENERATION_MODEL", "").strip(),
        "QDRANT_URL": os.getenv("QDRANT_URL", "http://127.0.0.1:6333").strip(),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RagConfigurationError(f"Faltan variables de entorno del RAG: {', '.join(missing)}.")
    if values["LLM_EMBEDDING_MODEL"] == values["LLM_GENERATION_MODEL"]:
        raise RagConfigurationError(
            "LLM_EMBEDDING_MODEL y LLM_GENERATION_MODEL deben ser modelos distintos "
            "(uno de embeddings y otro de chat)."
        )
    return RagSettings(
        llm_api_url=values["LLM_API_URL"],
        llm_api_key=values["LLM_API_KEY"],
        embedding_model=values["LLM_EMBEDDING_MODEL"],
        generation_model=values["LLM_GENERATION_MODEL"],
        qdrant_url=values["QDRANT_URL"],
    )


@lru_cache(maxsize=1)
def get_llm_client() -> OpenAI:
    """Cliente del gateway LLM de 4Geeks (compatible con OpenAI), uno por proceso."""
    settings = load_settings()
    return OpenAI(base_url=settings.llm_api_url, api_key=settings.llm_api_key, timeout=60, max_retries=2)


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=load_settings().qdrant_url, timeout=10)


# --- Chunking --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    source_document: str
    section: str
    language: str
    chunk_index: int
    text: str

    @property
    def point_id(self) -> str:
        """ID determinista: el mismo chunk siempre cae en el mismo punto de Qdrant."""
        key = f"{COMPANY}:{self.source_document}:{self.language}:{self.chunk_index}"
        return str(uuid.uuid5(POINT_NAMESPACE, key))

    @property
    def embedding_text(self) -> str:
        """Texto que se embebe: la sección da contexto a bloques que no nombran su tema."""
        return f"{self.section}\n\n{self.text}"

    def payload(self) -> dict[str, Any]:
        return {
            "company": COMPANY,
            "source_document": self.source_document,
            "section": self.section,
            "language": self.language,
            "chunk_index": self.chunk_index,
            "text": self.text,
        }


@dataclass
class _Unit:
    """Unidad semántica: un párrafo con su lista, o una regla suelta. `lead_in` es su frase de entrada."""

    lines: list[str]
    lead_in: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(([self.lead_in] if self.lead_in else []) + self.lines)


def _join_wrapped_lines(raw_lines: list[str]) -> list[str]:
    """Une las líneas cortadas a mano: cada párrafo y cada elemento de lista queda en una línea."""
    lines: list[str] = []
    for raw in raw_lines:
        stripped = raw.strip()
        if LIST_ITEM.match(raw) or not lines:
            lines.append(stripped)
        else:
            lines[-1] = f"{lines[-1]} {stripped}"
    return lines


def _is_list(line: str) -> bool:
    return bool(LIST_ITEM.match(line))


def _blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = [[]]
    for line in lines:
        if line.strip():
            blocks[-1].append(line)
        elif blocks[-1]:
            blocks.append([])
    return [_join_wrapped_lines(block) for block in blocks if block]


def _units(blocks: list[list[str]]) -> list[_Unit]:
    """Agrupa bloques sin separar una condición de su regla.

    - Una lista va con el párrafo que la introduce ("... funciona así:").
    - Una frase de entrada suelta ("TrackFlow trabaja con ... según el país:") se antepone al bloque siguiente.
    """
    units: list[_Unit] = []
    pending_lead_in: str | None = None
    for block in blocks:
        if all(_is_list(line) for line in block) and units and units[-1].lines[-1].endswith(":"):
            units[-1].lines.extend(block)
            continue
        if len(block) == 1 and block[0].endswith(":") and not _is_list(block[0]):
            pending_lead_in = f"{pending_lead_in}\n{block[0]}" if pending_lead_in else block[0]
            continue
        units.append(_Unit(lines=list(block), lead_in=pending_lead_in))
        pending_lead_in = None
    if pending_lead_in:
        units.append(_Unit(lines=[pending_lead_in]))
    return units


def _split_oversized(unit: _Unit) -> list[_Unit]:
    """Parte un bloque demasiado largo por líneas (elementos de lista) y, si no basta, por frases."""
    if len(unit.text) <= MAX_CHUNK_CHARS:
        return [unit]
    pieces: list[str] = []
    for line in unit.lines:
        pieces.extend(SENTENCE_END.split(line) if len(line) > MAX_CHUNK_CHARS else [line])
    parts: list[_Unit] = []
    current: list[str] = []
    for piece in pieces:
        candidate = _Unit(lines=current + [piece], lead_in=unit.lead_in)
        if current and len(candidate.text) > MAX_CHUNK_CHARS:
            parts.append(_Unit(lines=current, lead_in=unit.lead_in))
            current = [piece]
        else:
            current.append(piece)
    if current:
        parts.append(_Unit(lines=current, lead_in=unit.lead_in))
    return parts


def _label(unit: _Unit) -> str:
    """Etiqueta legible de un bloque: el rótulo antes de ':' si es corto, si no su primera cláusula.

    Una lista sin rótulo propio se etiqueta por la frase que la introduce.
    """
    first = unit.lead_in if unit.lead_in and _is_list(unit.lines[0]) else LIST_ITEM.sub("", unit.lines[0])
    prefix, colon, _ = first.partition(":")
    if colon and len(prefix.split()) <= MAX_LABEL_WORDS:
        return prefix.strip()
    clause = CLAUSE_END.split(first, maxsplit=1)[0].strip()
    if len(clause) <= MAX_LABEL_CHARS:
        return clause
    return clause[:MAX_LABEL_CHARS].rsplit(" ", 1)[0] + "…"


def parse_document(markdown: str, *, source_document: str, language: str) -> list[Chunk]:
    """Trocea un documento Markdown por encabezados y, dentro de cada sección, por unidades semánticas."""
    sections: list[tuple[list[str], list[str]]] = []  # (ruta de encabezados, líneas)
    path: list[tuple[int, str]] = []
    current: list[str] = []
    for line in markdown.splitlines():
        heading = HEADING.match(line)
        if heading:
            sections.append(([title for _, title in path], current))
            level = len(heading.group(1))
            path = [(lvl, title) for lvl, title in path if lvl < level] + [(level, heading.group(2))]
            current = []
        else:
            current.append(line)
    sections.append(([title for _, title in path], current))

    chunks: list[Chunk] = []
    for titles, lines in sections:
        units = [part for unit in _units(_blocks(lines)) for part in _split_oversized(unit)]
        base = SECTION_SEPARATOR.join(titles) or source_document
        for unit in units:
            section = f"{base}{SECTION_SEPARATOR}{_label(unit)}" if len(units) > 1 else base
            chunks.append(
                Chunk(
                    source_document=source_document,
                    section=section,
                    language=language,
                    chunk_index=len(chunks),
                    text=unit.text,
                )
            )
    return chunks


def load_chunks(directory: Path = KNOWLEDGE_BASE_DIR) -> list[Chunk]:
    """Lee y trocea todos los documentos `trackflow-*.<idioma>.md` de la base de conocimiento."""
    chunks: list[Chunk] = []
    paths = sorted(path for path in directory.glob(f"{COMPANY}-*.md") if DOCUMENT_NAME.match(path.name))
    if not paths:
        raise FileNotFoundError(f"No hay documentos {COMPANY}-*.md en {directory}.")
    for path in paths:
        name = DOCUMENT_NAME.match(path.name)
        assert name is not None
        chunks.extend(
            parse_document(
                path.read_text(encoding="utf-8"),
                source_document=name["source_document"],
                language=name["language"],
            )
        )
    return chunks


# --- Embeddings ------------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """Mismo preprocesado al indexar y al consultar: Unicode NFC y espacios colapsados."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def embed(text: str) -> list[float]:
    """Vector de `text` con el modelo de embeddings (nunca el de generación)."""
    clean = normalize_text(text)
    if not clean:
        raise ValueError("No se puede embeber un texto vacío.")
    model = load_settings().embedding_model
    try:
        response = get_llm_client().embeddings.create(model=model, input=clean)
    except openai.OpenAIError as error:
        logger.error("Fallo del modelo de embeddings %s: %s", model, type(error).__name__)
        raise RagServiceError("El modelo de embeddings no respondió.") from error
    if not response.data or not response.data[0].embedding:
        raise RagServiceError("El modelo de embeddings devolvió una respuesta vacía.")
    return list(response.data[0].embedding)


# --- Indexación ------------------------------------------------------------------------------


def index_chunks(client: QdrantClient, chunks: list[Chunk], vectors: list[list[float]]) -> None:
    """Recrea la colección y carga los puntos: volver a ejecutarlo nunca duplica."""
    if not chunks or len(chunks) != len(vectors):
        raise ValueError("Cada chunk necesita exactamente un vector.")
    dimension = len(vectors[0])
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=dimension, distance=DISTANCE),
    )
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(id=chunk.point_id, vector=vector, payload=chunk.payload())
            for chunk, vector in zip(chunks, vectors, strict=True)
        ],
        wait=True,
    )


def setup(directory: Path = KNOWLEDGE_BASE_DIR, *, client: QdrantClient | None = None) -> int:
    """Indexa la base de conocimiento en `trackflow_knowledge` y devuelve el número de chunks.

    Primero embebe todo y solo después recrea la colección: si el gateway falla a mitad,
    la colección anterior sigue sirviendo consultas.
    """
    chunks = load_chunks(directory)
    vectors = [embed(chunk.embedding_text) for chunk in chunks]
    try:
        index_chunks(client or get_qdrant_client(), chunks, vectors)
    except (UnexpectedResponse, ResponseHandlingException) as error:
        logger.error("Fallo al indexar en Qdrant: %s", type(error).__name__)
        raise RagServiceError("Qdrant no respondió al indexar la base de conocimiento.") from error
    logger.info("Colección %s indexada: %d chunks, dimensión %d.", COLLECTION_NAME, len(chunks), len(vectors[0]))
    return len(chunks)


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        total = setup()
    except (RagConfigurationError, RagServiceError, FileNotFoundError) as error:
        logger.error("%s", error)
        return 1
    by_document: dict[str, int] = {}
    for chunk in load_chunks():
        by_document[chunk.source_document] = by_document.get(chunk.source_document, 0) + 1
    print(f"{COLLECTION_NAME}: {total} chunks")
    for document, count in sorted(by_document.items()):
        print(f"  {document}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
