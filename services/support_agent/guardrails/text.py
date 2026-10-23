"""Normalización de texto para los guardrails: las reglas se escriben una vez, en minúsculas y sin acentos."""

from __future__ import annotations

import re
import unicodedata


INVISIBLE = re.compile(r"[​-‏ - ⁠-⁤﻿]")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")


def strip_invisible(text: str) -> str:
    """Quita caracteres de ancho cero y de control (se usan para esconder órdenes a las reglas)."""
    return CONTROL.sub("", INVISIBLE.sub("", text))


def normalize(text: str) -> str:
    """Minúsculas, sin acentos ni caracteres invisibles y con los espacios colapsados."""
    decomposed = unicodedata.normalize("NFKD", strip_invisible(text).casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_accents).strip()


def variants(text: str) -> tuple[str, str]:
    """El texto normalizado y otra versión sin signos dentro de las palabras ("i.g.n-o.r.a" → "ignora")."""
    normalized = normalize(text)
    joined = re.sub(r"(?<=[a-z])[^a-z0-9\s](?=[a-z])", "", normalized)
    return normalized, re.sub(r"[^a-z0-9#\s]", " ", joined)


def sentences(line: str) -> list[str]:
    return [part for part in SENTENCE_END.split(line) if part]
