"""Agente orquestador: descompone la RFP en una subtarea por departamento.

Decide qué departamentos del BRIEFING aplican según el alcance que pide el cliente y, para cada uno, qué párrafos
del documento le corresponden. Los workers reciben esos párrafos literales (por número), nunca un resumen.

Lo que el modelo no puede decidir lo valida el código:
- un `department_id` que no es del BRIEFING no crea un worker: se registra en `out_of_scope` para que Ventas lo vea.
  El id del servicio (`last_mile`) se acepta como alias de su departamento (`lastmile`): el modelo los confunde;
- todo servicio que el cliente pide en los metadatos tiene su departamento activo, aunque el modelo lo omita;
- los números de párrafo inexistentes se ignoran; si un departamento se queda sin párrafos, recibe el documento
  entero (recortado) para no trabajar a ciegas.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from data.pipelines.rfp_intake import llm
from data.pipelines.rfp_intake.departments import DEPARTMENTS, department_catalog
from data.pipelines.rfp_intake.document import numbered


logger = logging.getLogger("trackflow.rfp_intake")

AGENT = "orchestrator"
MAX_ORCHESTRATOR_CHARS = 40_000

SYSTEM_PROMPT = f"""Eres el agente orquestador del análisis de RFPs de TrackFlow. Recibes los metadatos de la RFP y
el documento dividido en párrafos numerados ([P1], [P2]…). Reparte el análisis entre estos departamentos (usa
exactamente estos identificadores):

{department_catalog()}

Reglas:
- Activa un departamento solo si el cliente pide ese servicio. Si el cliente dice que no lo necesita (p. ej. usa
  su propio transportista), no lo actives.
- Para cada departamento activo indica en "focus" qué tiene que analizar (una frase) y en "paragraph_ids" los
  números de los párrafos relevantes para él (incluye los de contexto general: cliente, volumen, plazos).
- Lo que el cliente pide y no cubre ningún departamento (p. ej. integración con su ERP) va en "out_of_scope",
  como frases cortas en español.

Responde solo con JSON:
{{"departments": [{{"department_id": "...", "focus": "...", "paragraph_ids": [1, 2]}}],
  "out_of_scope": ["..."]}}"""


class Assignment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    department_id: str
    focus: str = Field(min_length=1, max_length=400)
    paragraph_ids: list[int] = Field(default_factory=list)


class OrchestratorOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    departments: list[Assignment] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


def plan(metadata: dict[str, Any], paragraphs: list[str]) -> dict[str, Any]:
    prompt = (
        f"METADATOS DE LA RFP:\n{json.dumps(metadata, ensure_ascii=False)}\n\n"
        f"{llm.as_document(numbered(paragraphs)[:MAX_ORCHESTRATOR_CHARS])}"
    )
    output = llm.ask_json(AGENT, SYSTEM_PROMPT, prompt, OrchestratorOutput)
    return validate_plan(output, len(paragraphs), metadata.get("services_requested", []))


DEPARTMENT_BY_SERVICE = {department.service.value: department.department_id for department in DEPARTMENTS.values()}


def validate_plan(
    output: OrchestratorOutput, paragraph_count: int, services_requested: list[str] | None = None
) -> dict[str, Any]:
    assignments: list[dict[str, Any]] = []
    out_of_scope = [item.strip() for item in output.out_of_scope if item.strip()]
    seen: set[str] = set()
    for assignment in output.departments:
        department_id = assignment.department_id.strip().lower()
        department_id = DEPARTMENT_BY_SERVICE.get(department_id, department_id)
        if department_id not in DEPARTMENTS:
            logger.warning("orchestrator departamento fuera del BRIEFING: %r (va a out_of_scope).", department_id)
            out_of_scope.append(f"Departamento no reconocido «{assignment.department_id}»: {assignment.focus}")
            continue
        if department_id in seen:
            continue
        seen.add(department_id)
        ids = sorted({i for i in assignment.paragraph_ids if 1 <= i <= paragraph_count})
        if not ids:
            logger.warning("orchestrator %s sin párrafos válidos: recibe el documento completo.", department_id)
            ids = list(range(1, paragraph_count + 1))
        assignments.append({"department_id": department_id, "focus": assignment.focus.strip(), "paragraph_ids": ids})
    for service in services_requested or []:
        department_id = DEPARTMENT_BY_SERVICE.get(service)
        if department_id and department_id not in seen:
            logger.warning("orchestrator omitió %s aunque el cliente pide %s: se activa.", department_id, service)
            seen.add(department_id)
            focus = f"Analizar lo que pide el cliente para {DEPARTMENTS[department_id].name}."
            assignments.append(
                {"department_id": department_id, "focus": focus, "paragraph_ids": list(range(1, paragraph_count + 1))}
            )
    # Orden estable del BRIEFING (warehouse, lastmile, reverse) para que el resultado no dependa del modelo.
    order = list(DEPARTMENTS)
    assignments.sort(key=lambda item: order.index(item["department_id"]))
    return {"assignments": assignments, "out_of_scope": list(dict.fromkeys(out_of_scope))}
