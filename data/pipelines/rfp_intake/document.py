"""Preparación del documento antes de que lo lea ningún agente.

- `pdf_to_markdown`: PDF → Markdown con MarkItDown. Es el primer paso del grafo: los agentes solo ven Markdown,
  que cuesta menos tokens y trae menos ruido que el PDF.
- `split_paragraphs`: párrafos numerados. El orquestador elige párrafos por número y los workers reciben esos
  párrafos literales, nunca un resumen del modelo.
- `readability_metrics`: métricas de `py-readability-metrics` más el recuento de palabras y una estimación de
  tokens. Sirven para anticipar el costo de procesar el documento, no como nota literaria.
- `numbers_in` / `unsupported_numbers`: base de la regla "nunca inventes cifras" de los workers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from markitdown import StreamInfo
from markitdown.converters import PdfConverter
from readability import Readability
from readability.exceptions import ReadabilityException


logger = logging.getLogger("trackflow.rfp_intake")

# pdfminer deja glifos sin mapear (viñetas) como `(cid:127)`.
UNMAPPED_GLYPH = re.compile(r"\(cid:\d+\)")
BLANK_LINES = re.compile(r"\n\s*\n+")
# Cifras con separadores de miles o decimales: `5,000`, `15.000`, `30%`, `2026`.
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# Aproximación habitual para estimar el costo: ~4 caracteres por token.
CHARS_PER_TOKEN = 4
PDF_STREAM_INFO = StreamInfo(extension=".pdf", mimetype="application/pdf")


class DocumentConversionError(RuntimeError):
    """El PDF no se pudo convertir a Markdown o no contiene texto."""


@dataclass(frozen=True)
class ReadabilityMetrics:
    word_count: int
    estimated_tokens: int
    flesch_kincaid_grade: float | None
    gunning_fog: float | None
    flesch_reading_ease: float | None


def pdf_to_markdown(pdf_path: str | Path) -> str:
    # El conversor de PDF de MarkItDown, no `MarkItDown().convert`: ese cae a texto plano con un PDF corrupto y
    # dejaría pasar los bytes crudos a los agentes.
    try:
        with open(pdf_path, "rb") as stream:
            result = PdfConverter().convert(stream, PDF_STREAM_INFO)
    except Exception as error:  # pdfminer lanza varias clases propias según el defecto del archivo.
        raise DocumentConversionError(f"No se pudo convertir el PDF a Markdown ({type(error).__name__}).") from error
    markdown = clean_markdown(result.markdown or "")
    if not markdown:
        raise DocumentConversionError("El PDF no contiene texto extraíble (¿es una imagen escaneada?).")
    return markdown


def clean_markdown(text: str) -> str:
    text = UNMAPPED_GLYPH.sub("-", text.replace("\r\n", "\n"))
    lines = [line.rstrip() for line in text.split("\n")]
    return BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def split_paragraphs(markdown: str) -> list[str]:
    return [block.strip() for block in markdown.split("\n\n") if block.strip()]


def numbered(paragraphs: list[str]) -> str:
    return "\n\n".join(f"[P{index}] {paragraph}" for index, paragraph in enumerate(paragraphs, start=1))


def readability_metrics(markdown: str) -> ReadabilityMetrics:
    words = len(markdown.split())
    tokens = max(1, round(len(markdown) / CHARS_PER_TOKEN))
    grade = fog = ease = None
    try:
        ensure_sentence_tokenizer()
        scores = Readability(markdown)
        grade = round(scores.flesch_kincaid().score, 2)
        fog = round(scores.gunning_fog().score, 2)
        ease = round(scores.flesch().score, 2)
    except ReadabilityException:
        # La librería exige al menos 100 palabras; un correo corto se procesa igual, sin estas tres métricas.
        logger.info("readability sin métricas: el documento tiene %s palabras (mínimo 100).", words)
    except LookupError:
        logger.warning("readability sin métricas: falta el tokenizador `punkt_tab` de NLTK y no se pudo descargar.")
    return ReadabilityMetrics(words, tokens, grade, fog, ease)


def ensure_sentence_tokenizer() -> None:
    import nltk

    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        # La imagen de Docker ya lo trae; en local se descarga una sola vez.
        nltk.download("punkt_tab", quiet=True)
        nltk.data.find("tokenizers/punkt_tab")


def normalize_number(token: str) -> str:
    """`5,000` → `5000`, `08` → `8`: misma cifra con o sin separadores."""
    digits = re.sub(r"[.,]", "", token).lstrip("0")
    return digits or "0"


def numbers_in(text: str) -> set[str]:
    found: set[str] = set()
    for match in NUMBER.finditer(text):
        token = match.group()
        found.add(normalize_number(token))
        # `15.000` también puede citarse como `15`; `2026-08-28` aporta 2026, 08 y 28.
        found.update(normalize_number(part) for part in re.split(r"[.,]", token) if part)
    return found


def unsupported_numbers(text: str, allowed: set[str]) -> list[str]:
    """Cifras de `text` que no aparecen en la fuente (`allowed`, salida de `numbers_in`)."""
    return [match.group() for match in NUMBER.finditer(text) if normalize_number(match.group()) not in allowed]
