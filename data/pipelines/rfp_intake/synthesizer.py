"""Agente synthesizer: consolida las secciones de los workers en el resultado que lee Ventas.

La estructura de workstreams (departamento, responsable, aspectos clave, qué pedirle, preguntas abiertas) se arma
en código a partir de las secciones: el modelo no puede cambiar a quién se le pide qué. El modelo solo redacta el
resumen, los siguientes pasos y señala contradicciones entre secciones (no las resuelve: eso es del árbitro de la
Parte 3).

`build_handoff` produce el contrato de enrutamiento hacia la Parte 2 (`rfp_intake.handoff.v1`, ver README).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from data.pipelines.rfp_intake import llm


AGENT = "synthesizer"
HANDOFF_VERSION = "rfp_intake.handoff.v1"
NEXT_STAGE = "generando_borrador"

SYSTEM_PROMPT = """Eres el agente synthesizer del análisis de RFPs de TrackFlow. Recibes los metadatos de la RFP,
lo que queda fuera del alcance de los departamentos y el análisis de cada departamento activo. Redacta para el
equipo de Ventas (Miguel Torres, Commercial Director):
- "summary": 2-4 frases en español con quién es el cliente, qué pide, en qué país y moneda, y para cuándo.
- "next_steps": acciones concretas para Ventas, nombrando al responsable del departamento al que hay que pedir cada
  cosa (máximo 6).
- "conflicts": contradicciones entre secciones o con los metadatos (p. ej. dos volúmenes distintos); [] si no hay.
  Solo señálalas: no las resuelvas.

Usa solo la información recibida; no añadas cifras nuevas.
Responde solo con JSON: {"summary": "...", "next_steps": [...], "conflicts": [...]}"""


class SynthesizerOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=1, max_length=1500)
    next_steps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


def synthesize(metadata: dict[str, Any], sections: list[dict[str, Any]], out_of_scope: list[str]) -> dict[str, Any]:
    prompt = json.dumps(
        {"metadata": metadata, "out_of_scope": out_of_scope, "departments": sections}, ensure_ascii=False
    )
    output = llm.ask_json(AGENT, SYSTEM_PROMPT, prompt, SynthesizerOutput)
    return {
        "summary": output.summary.strip(),
        "next_steps": [step.strip() for step in output.next_steps if step.strip()][:6],
        "conflicts": [item.strip() for item in output.conflicts if item.strip()],
        "out_of_scope": out_of_scope,
        "workstreams": [
            {
                "department_id": section["department_id"],
                "department_name": section["department_name"],
                "responsible": section["responsible"],
                "key_aspects": section["key_aspects"],
                "requested_inputs": section["requested_inputs"],
                "open_questions": section["open_questions"],
            }
            for section in sections
        ],
    }


def build_handoff(ticket_id: str, rfp_id: str, metadata: dict[str, Any], synthesis: dict[str, Any]) -> dict[str, Any]:
    """Contrato de entrada de la Parte 2: todo lo necesario para generar borradores sin volver a leer el PDF."""
    return {
        "version": HANDOFF_VERSION,
        "ticket_id": ticket_id,
        "rfp_id": rfp_id,
        "next_stage": NEXT_STAGE,
        "currency": metadata.get("currency"),
        "client_country": metadata.get("client_country"),
        "departments": [workstream["department_id"] for workstream in synthesis["workstreams"]],
        "workstreams": synthesis["workstreams"],
        "summary": synthesis["summary"],
        "conflicts": synthesis["conflicts"],
    }
