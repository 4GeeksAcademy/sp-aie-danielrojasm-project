"""Guard de salida: valida la respuesta del modelo antes de devolverla al usuario.

Tres comprobaciones, en este orden:

1. **Fuga de instrucciones internas** (`security`): la marca `PROMPT_CANARY`, las etiquetas del prompt o un trozo
   literal de la jerarquía de instrucciones. La respuesta entera se sustituye por `LEAK_REFUSAL`.
2. **Datos sensibles del CONTEXT** (`content`): correos, direcciones, coordenadas, ubicaciones internas de almacén,
   tarifas negociadas con transportistas y pedidos que no son de la sesión. Se retira la frase (`REDACTED`).
3. **Formato** (`structural`): una respuesta de dominio termina con su línea "Fuente:"; si el modelo la pegó a la
   última frase, se pasa a su propia línea, y si falta, se añade con las secciones del contexto. Una respuesta de
   charla breve no supera `SMALL_TALK_MAX_CHARS` y termina reconduciendo.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from services.support_agent.guardrails.events import GuardrailEvent
from services.support_agent.guardrails.input_guard import PURPOSE, SMALL_TALK_REDIRECT, unauthorized_orders
from services.support_agent.guardrails.text import normalize, sentences
from services.support_agent.prompt import PROMPT_CANARY, SMALL_TALK_PROMPT, SYSTEM_PROMPT


Mode = Literal["answer", "small_talk"]

LEAK_REFUSAL = f"No puedo compartir mis instrucciones internas. {PURPOSE}"
REDACTED = "[dato restringido retirado]"
NO_SOURCE = "Fuente: sin información en la base de conocimiento"
# "… con la marca. Fuente: Política de Devoluciones": la fuente al final de la última frase, no en su propia línea.
INLINE_SOURCE = re.compile(r"\s(Fuente: [^\n]+)$")
SMALL_TALK_MAX_CHARS = 400
SMALL_TALK_FALLBACK = "Eso queda fuera de lo que puedo consultar."

LEAK_MARKERS = (
    PROMPT_CANARY.casefold(),
    "<mensaje_usuario",
    "</mensaje_usuario",
    "<contenido_externo",
    "jerarquia de instrucciones",
    "modo charla breve",
    "propuesta_memoria",
)
SHINGLE_WORDS = 8

SENSITIVE = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "street_address": re.compile(
        r"\b(calle|c/|avenida|avda|paseo|carretera|poligono|nave|street|avenue|boulevard|blvd|road)\b.{0,40}\d"
        r"|\b\d{1,5}\s+\w+(\s\w+)?\s+(street|st|avenue|ave|blvd|road|rd|drive)\b"
    ),
    "coordinates": re.compile(r"-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}"),
    "warehouse_internal_location": re.compile(
        r"\b(muelle|pasillo|estanteria|rack|dock|aisle|ruta interna|internal route)\s+(n[o.]*\s*)?"
        r"([a-z]?\d{1,4}[a-z]?|[a-z])\b"
    ),
    "carrier_negotiated_rate": re.compile(
        r"\b(tarifas? negociadas?|negotiated rates?|condiciones comerciales)\b"
        r"|\b(ups|fedex|dhl|mrw|seur)\b.{0,60}(\d+([.,]\d+)?\s*(usd|eur|dolares|euros|\$|€)|[$€]\s*\d)"
        r"|(\d+([.,]\d+)?\s*(usd|eur|dolares|euros|\$|€)|[$€]\s*\d).{0,60}\b(ups|fedex|dhl|mrw|seur)\b"
    ),
}


class OutputCheck(BaseModel):
    answer: str
    events: list[GuardrailEvent] = []


def check_output(
    answer: str,
    *,
    mode: Mode = "answer",
    sections: Iterable[str] = (),
    authorized_orders: Iterable[str] = (),
) -> OutputCheck:
    if leaks_instructions(answer):
        return OutputCheck(
            answer=LEAK_REFUSAL,
            events=[_event("security", "block", "system_prompt_leak")],
        )
    events: list[GuardrailEvent] = []
    answer, kinds = redact_sensitive(answer, list(authorized_orders))
    events.extend(_event("content", "redact", kind) for kind in kinds)
    if mode == "small_talk":
        answer, repaired = _small_talk_format(answer)
        if repaired:
            events.append(_event("structural", "repair", "small_talk_too_long"))
    elif not has_source_line(answer):
        inline = INLINE_SOURCE.search(answer.rstrip())
        if inline:
            answer = f"{answer.rstrip()[: inline.start()].rstrip()}\n{inline.group(1)}"
            events.append(_event("structural", "repair", "inline_source_line"))
        else:
            unique_sections = list(dict.fromkeys(section for section in sections if section))
            source = f"Fuente: {'; '.join(unique_sections)}" if unique_sections else NO_SOURCE
            answer = f"{answer.rstrip()}\n{source}"
            events.append(_event("structural", "repair", "missing_source_line"))
    return OutputCheck(answer=answer, events=events)


def leaks_instructions(answer: str) -> bool:
    normalized = normalize(answer)
    if any(marker in normalized for marker in LEAK_MARKERS):
        return True
    return bool(_shingles(normalized) & _CONFIDENTIAL_SHINGLES)


def redact_sensitive(answer: str, authorized_orders: list[str]) -> tuple[str, list[str]]:
    """La respuesta sin las frases con datos sensibles, y los tipos de dato retirados (sin repetir)."""
    kinds: list[str] = []
    lines = []
    for line in answer.split("\n"):
        if line.strip().startswith("Fuente:"):
            lines.append(line)
            continue
        kept = []
        for sentence in sentences(line):
            found = _sensitive_kinds(sentence, authorized_orders)
            kinds.extend(kind for kind in found if kind not in kinds)
            kept.append(REDACTED if found else sentence)
        lines.append(" ".join(kept))
    return "\n".join(lines), kinds


def has_source_line(answer: str) -> bool:
    return any(line.strip().startswith("Fuente:") for line in answer.split("\n"))


def _sensitive_kinds(sentence: str, authorized_orders: list[str]) -> list[str]:
    normalized = normalize(sentence)
    kinds = [kind for kind, pattern in SENSITIVE.items() if pattern.search(normalized)]
    if unauthorized_orders(sentence, authorized_orders):
        kinds.append("unauthorized_order")
    return kinds


def _small_talk_format(answer: str) -> tuple[str, bool]:
    text = answer.strip()
    repaired = len(text) > SMALL_TALK_MAX_CHARS
    if repaired:
        text = SMALL_TALK_FALLBACK
    if not text.endswith(SMALL_TALK_REDIRECT):
        text = f"{text}\n\n{SMALL_TALK_REDIRECT}"
    return text, repaired


def _shingles(normalized: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", normalized)
    return {tuple(words[i : i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)}


def _confidential_text() -> str:
    """Las partes del prompt que no aparecen en una respuesta legítima (las reglas de negocio sí se citan)."""
    hierarchy = SYSTEM_PROMPT.split("JERARQUÍA DE INSTRUCCIONES", 1)[1].split("DOMINIO:", 1)[0]
    return f"{hierarchy}\n{SMALL_TALK_PROMPT}"


_CONFIDENTIAL_SHINGLES = _shingles(normalize(_confidential_text()))


def _event(failure_type: str, action: str, reason: str) -> GuardrailEvent:
    return GuardrailEvent(guardrail="output_guard", failure_type=failure_type, action=action, reason=reason)
