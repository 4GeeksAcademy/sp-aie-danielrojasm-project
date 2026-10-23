"""Aislamiento del contenido externo: lo que traen el RAG, el gestor de incidencias y la memoria nunca es una orden.

Tres medidas, de la más barata a la más visible:

1. `neutralize()` quita caracteres invisibles y las etiquetas que delimitan el prompt (`<mensaje_usuario>`,
   `<contenido_externo>`, `<system>`…), para que un texto no pueda cerrar su bloque y abrir uno "del sistema".
2. `sanitize_fragment()` retira cada frase que intenta cambiar las instrucciones del agente (mismos patrones que el
   guard de entrada) y la sustituye por `REMOVED_INSTRUCTION`.
3. `prompt.build_messages()` envía cada fragmento en el mensaje del usuario, dentro de `<contenido_externo>`, nunca en
   el mensaje de sistema; el system prompt declara que ese bloque son datos.
"""

from __future__ import annotations

import re
from typing import Any

from services.support_agent.guardrails.input_guard import find_instruction_override
from services.support_agent.guardrails.text import sentences, strip_invisible


REMOVED_INSTRUCTION = "[instrucción incrustada retirada]"
PROMPT_TAG = re.compile(
    r"<\s*/?\s*(mensaje_usuario|contenido_externo|system|sistema|instructions?|assistant|developer)\b[^>]*>",
    re.IGNORECASE,
)
# Campos de un fragmento que llegan al modelo como texto libre; el resto (ids, idioma) no se envía.
TEXT_FIELDS = ("text", "section")
SOURCE_LABELS = {
    "incident-manager": "gestor de incidencias",
    "agent-memory": "memoria aprobada",
}


def neutralize(text: str) -> str:
    return PROMPT_TAG.sub("[etiqueta retirada]", strip_invisible(text))


def sanitize_text(text: str) -> tuple[str, int]:
    """El texto sin etiquetas del prompt ni frases con órdenes; devuelve también cuántas frases se retiraron."""
    removed = 0
    lines = []
    for line in neutralize(text).split("\n"):
        kept = []
        for sentence in sentences(line):
            if find_instruction_override(sentence):
                removed += 1
                kept.append(REMOVED_INSTRUCTION)
            else:
                kept.append(sentence)
        lines.append(" ".join(kept))
    return "\n".join(lines), removed


def sanitize_fragment(fragment: dict[str, Any]) -> tuple[dict[str, Any], int]:
    clean = dict(fragment)
    removed = 0
    for field in TEXT_FIELDS:
        if isinstance(clean.get(field), str):
            clean[field], count = sanitize_text(clean[field])
            removed += count
    return clean, removed


def source_label(fragment: dict[str, Any]) -> str:
    """Origen del fragmento para el atributo `origen` del bloque (`base de conocimiento` por defecto)."""
    return SOURCE_LABELS.get(str(fragment.get("source_document")), "base de conocimiento")
