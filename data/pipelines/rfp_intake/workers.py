"""Agentes worker: un analista por departamento (`warehouse`, `lastmile`, `reverse`).

Cada worker recibe solo lo que necesita del estado compartido: los metadatos de la RFP, la tarea que le asignó el
orquestador y los párrafos literales que le corresponden. Nunca el documento entero ni el trabajo de otro worker.

Devuelve tres listas para Ventas:
- `key_aspects`: lo que la RFP pide o condiciona en ese departamento;
- `requested_inputs`: lo que Ventas tiene que pedirle al responsable del departamento para cotizar;
- `open_questions`: datos que faltan en la RFP y hay que preguntar al cliente.

Regla "nunca inventes" (BRIEFING §2.3), aplicada en código: una frase con una cifra que no aparece en los párrafos
ni en los metadatos se descarta y se convierte en pregunta abierta. Si el departamento depende del volumen mensual
y la RFP no lo da, siempre queda una pregunta abierta pidiéndolo.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from data.pipelines.rfp_intake import llm
from data.pipelines.rfp_intake.departments import DEPARTMENTS, VOLUME_DEPENDENT_DEPARTMENTS
from data.pipelines.rfp_intake.document import numbers_in, unsupported_numbers


logger = logging.getLogger("trackflow.rfp_intake")

MAX_ITEMS = 8
MISSING_VOLUME_QUESTION = (
    "La RFP no indica el volumen mensual de pedidos: pedirlo al cliente antes de cotizar (no se estima)."
)

SYSTEM_PROMPT = """Eres el analista de {name} de TrackFlow (responsable: {responsible}).
Tu departamento aporta a la propuesta: {contribution}

Recibes los metadatos de una RFP, la tarea que te asignó el orquestador y SOLO los extractos del documento que
te corresponden. Prepara para el equipo de Ventas:
- "key_aspects": lo que el cliente pide o condiciona en tu área (frases cortas, con las cifras tal como aparecen).
- "requested_inputs": lo que Ventas tiene que pedirle a {responsible} para poder cotizar (p. ej. una tarifa o una
  capacidad concreta para lo que pide el cliente).
- "open_questions": datos que faltan en la RFP y hay que preguntar al cliente.

Reglas: usa solo cifras que aparezcan en los extractos o en los metadatos; nunca estimes volúmenes, pallets, SKUs,
pedidos, precios ni plazos. Si falta un dato necesario, pregúntalo en "open_questions". Máximo {max_items}
elementos por lista, en español.

Responde solo con JSON: {{"key_aspects": [...], "requested_inputs": [...], "open_questions": [...]}}"""


class WorkerOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key_aspects: list[str] = Field(default_factory=list)
    requested_inputs: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


def analyze(department_id: str, focus: str, metadata: dict[str, Any], excerpts: list[str]) -> dict[str, Any]:
    department = DEPARTMENTS[department_id]
    system_prompt = SYSTEM_PROMPT.format(
        name=department.name,
        responsible=department.responsible,
        contribution=department.contribution,
        max_items=MAX_ITEMS,
    )
    user_prompt = (
        f"METADATOS DE LA RFP:\n{json.dumps(metadata, ensure_ascii=False)}\n\n"
        f"TAREA DEL ORQUESTADOR: {focus}\n\n"
        f"{llm.as_document(chr(10).join(excerpts))}"
    )
    output = llm.ask_json(f"{department_id}_worker", system_prompt, user_prompt, WorkerOutput)
    return ground(department_id, output, metadata, excerpts)


def ground(department_id: str, output: WorkerOutput, metadata: dict[str, Any], excerpts: list[str]) -> dict[str, Any]:
    """Aplica la regla de cifras y la pregunta obligatoria del volumen. Devuelve la sección del departamento."""
    allowed = numbers_in("\n".join(excerpts)) | numbers_in(json.dumps(metadata, ensure_ascii=False))
    open_questions = _grounded(department_id, "open_questions", output.open_questions, allowed, [])
    key_aspects = _grounded(department_id, "key_aspects", output.key_aspects, allowed, open_questions)
    requested_inputs = _grounded(department_id, "requested_inputs", output.requested_inputs, allowed, open_questions)
    if department_id in VOLUME_DEPENDENT_DEPARTMENTS and metadata.get("monthly_volume") is None:
        open_questions.insert(0, MISSING_VOLUME_QUESTION)
    department = DEPARTMENTS[department_id]
    return {
        "department_id": department_id,
        "department_name": department.name,
        "responsible": department.responsible,
        "key_aspects": key_aspects[:MAX_ITEMS],
        "requested_inputs": requested_inputs[:MAX_ITEMS],
        "open_questions": list(dict.fromkeys(open_questions))[: MAX_ITEMS + 1],
    }


def _grounded(
    department_id: str, field: str, items: list[str], allowed: set[str], open_questions: list[str]
) -> list[str]:
    kept: list[str] = []
    for item in (text.strip() for text in items):
        if not item:
            continue
        invented = unsupported_numbers(item, allowed)
        if invented:
            logger.warning(
                "%s_worker %s descartado: cifras que no están en la RFP %s.", department_id, field, invented
            )
            open_questions.append(f"Confirmar con el cliente (cifra no presente en la RFP): {item}")
            continue
        kept.append(item)
    return kept
