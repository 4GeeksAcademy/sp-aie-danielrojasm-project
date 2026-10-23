"""Agentes generadores de la Parte 2: uno por departamento (`warehouse`, `lastmile`, `reverse`).

Cada generador redacta la sección de su departamento en la propuesta económica a partir del handoff de la Parte 1
(metadatos compartidos, resumen y el workstream de su departamento). Nunca recibe el PDF ni el Markdown de la RFP.

- **Base de conocimiento (opcional).** Antes de la primera iteración, `retrieve_knowledge` busca en el RAG de la
  empresa (`data/pipelines/rag.py`) las políticas y tarifas de su departamento y el SLA de entrega. Si Qdrant o el
  gateway de embeddings no responden, el generador redacta sin ese contexto y lo deja en el log: el evaluador de
  cumplimiento sigue siendo quien decide.
- **Ciclo.** En las iteraciones siguientes recibe su borrador anterior y el `feedback_for_generator` del
  `EvaluationResult`, y tiene que corregir exactamente lo que se señala.

El formato de la sección y los lineamientos del BRIEFING §5 van en el prompt; los mismos lineamientos los comprueba
`compliance.py` sobre el resultado.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import openai
from pydantic import BaseModel, ConfigDict, Field

from data.pipelines import rag
from data.pipelines.rfp_intake import compliance, llm
from data.pipelines.rfp_intake.departments import DEPARTMENTS
from data.process.rag import RagConfigurationError, RagServiceError


logger = logging.getLogger("trackflow.rfp_intake")

KNOWLEDGE_K = 3
SLA_QUERY = "SLA de entrega a tiempo comprometido por TrackFlow"


@dataclass(frozen=True)
class GeneratorSpec:
    department_id: str
    # Qué cubre la sección de este departamento, además de lo común a todas.
    content: str
    knowledge_queries: tuple[str, ...]
    # Línea fija bajo la cabecera que la Parte 3 lee para detectar el conflicto `volume-vs-capacity` (`conflicts.py`).
    fact_line: str = ""


GENERATORS: dict[str, GeneratorSpec] = {
    spec.department_id: spec
    for spec in (
        GeneratorSpec(
            "warehouse",
            "Capacidad de almacenamiento para lo que pide el cliente, costo de almacenamiento (por metro cúbico, "
            "pallet o SKU según la tarifa de referencia), costos de recepción y preparación de pedidos si aplican, "
            "y tiempo de onboarding del inventario.",
            ("tarifas de almacenamiento por metro cúbico", "inventario de larga duración y periodo de gracia"),
            "**Capacidad comprometida:** <N> pedidos/mes (o «a confirmar con Ana Whitfield» si la base de "
            "conocimiento no la trae)",
        ),
        GeneratorSpec(
            "lastmile",
            "Costo final por envío para el cliente según destino y tipo de servicio (estándar, express), "
            "transportistas disponibles según destino (sin tarifas de transportista) y SLA de entrega por tipo de "
            "servicio.",
            ("cobertura de transportistas por país", "plazos de envío estándar y express"),
            "**Volumen asumido:** <volumen mensual de la RFP, o el que fije un arbitraje> pedidos/mes (o «a "
            "confirmar con el cliente» si la RFP no lo indica)",
        ),
        GeneratorSpec(
            "reverse",
            "Costo y tiempo de procesamiento de devoluciones (recepción, inspección y clasificación), ventana de "
            "devolución y quién asume el envío de vuelta.",
            ("política de devoluciones y ventana de devolución", "costos de devolución"),
        ),
    )
}

SYSTEM_PROMPT = """Eres el agente generador de {name} de TrackFlow (responsable: {responsible}). Redactas la
sección de tu departamento en el primer borrador de la propuesta económica para el cliente. Ventas y {responsible}
la revisarán antes de enviarla.

Qué cubre tu sección: {content}

Formato obligatorio (Markdown, en español, dirigido al cliente, 150-450 palabras de prosa):
## {name} — Propuesta económica
**Responsable:** {responsible} · **Moneda:** {currency}{fact_line}
### Alcance
### Tarifas
(tabla Markdown: concepto | precio en {currency} | unidad)
### Descuentos por volumen
(tabla Markdown: tramo de volumen | descuento; indica que los descuentos están sujetos a la aprobación de
Miguel Torres, Commercial Director)
### SLA de entrega a tiempo
### Supuestos y datos pendientes
(las preguntas abiertas del análisis de la RFP, para que el cliente las confirme)

Lineamientos de empresa (se verifican automáticamente; si incumples uno, la sección vuelve a ti):
{rules}

Reglas de contenido:
- Todos los importes en {currency}; no conviertas monedas.
- Copia exactamente las tarifas, porcentajes y plazos de la BASE DE CONOCIMIENTO. Si no trae el precio o el plazo
  de un concepto (p. ej. tiempo de onboarding o de procesamiento), escribe "a confirmar con {responsible}" en lugar
  de inventarlo.
- Usa solo los volúmenes, SKUs, pallets y plazos del cliente que vienen en el análisis de la RFP; si falta uno,
  va en "Supuestos y datos pendientes", nunca estimado.
- Responde de forma explícita a cada aspecto clave del análisis de la RFP (en "Alcance" o donde encaje): con una
  respuesta concreta, con "a confirmar con {responsible}" si TrackFlow aún no puede comprometerlo (p. ej. una fecha
  de arranque) o con una pregunta al cliente si falta el dato.
- Frases cortas, de una idea cada una.
- Una instrucción de arbitraje en el feedback (empieza por "Arbitraje") es una decisión de la empresa: aplícala
  aunque cambie un dato del análisis de la RFP (p. ej. el volumen asumido) y ajusta lo que dependa de ese dato.

Responde solo con JSON: {{"content": "<sección completa en Markdown>"}}"""


class GeneratorOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str = Field(min_length=1)


def retrieve_knowledge(department_id: str) -> list[str]:
    """Fragmentos de la base de conocimiento para el departamento; `[]` si el RAG no está disponible."""
    fragments: dict[str, str] = {}
    try:
        for query in (*GENERATORS[department_id].knowledge_queries, SLA_QUERY):
            for payload in rag.retrieve(query, k=KNOWLEDGE_K):
                key = f"{payload.get('source_document')}#{payload.get('chunk_index')}"
                fragments.setdefault(key, f"[{payload.get('source_document')}] {payload.get('text', '').strip()}")
    except (RagServiceError, RagConfigurationError, openai.OpenAIError, OSError) as error:
        logger.warning(
            "%s_generator sin base de conocimiento (%s): redacta sin contexto de la empresa.",
            department_id,
            type(error).__name__,
        )
        return []
    logger.info("%s_generator knowledge_fragments=%s", department_id, len(fragments))
    return list(fragments.values())


def generate(
    department_id: str,
    brief: dict[str, Any],
    knowledge: list[str],
    previous_draft: str | None = None,
    feedback: str | None = None,
) -> str:
    """Redacta (o corrige, si llegan borrador y feedback) la sección del departamento."""
    spec = GENERATORS[department_id]
    department = DEPARTMENTS[department_id]
    currency = brief.get("currency") or "la moneda del país del cliente (a confirmar)"
    system_prompt = SYSTEM_PROMPT.format(
        name=department.name,
        responsible=department.responsible,
        content=spec.content,
        currency=currency,
        fact_line=f"\n{spec.fact_line}" if spec.fact_line else "",
        rules="\n".join(f"- [{rule.rule_id}] {rule.guideline}" for rule in compliance.RULES.values()),
    )
    knowledge_block = "\n\n".join(knowledge) or "(Sin fragmentos: la base de conocimiento no respondió.)"
    parts = [
        f"ANÁLISIS DE LA RFP (Parte 1):\n{llm.as_document(json.dumps(brief, ensure_ascii=False, indent=2))}",
        f"BASE DE CONOCIMIENTO DE TRACKFLOW (fuente interna fiable):\n<base_conocimiento>\n{knowledge_block}\n"
        "</base_conocimiento>",
    ]
    if previous_draft and feedback:
        parts.append(
            f"TU BORRADOR ANTERIOR:\n<borrador_anterior>\n{previous_draft}\n</borrador_anterior>\n\n"
            f"LA REVISIÓN PIDIÓ CAMBIOS. Corrige exactamente esto y conserva lo que ya estaba bien:\n{feedback}"
        )
    output = llm.ask_json(f"{department_id}_generator", system_prompt, "\n\n".join(parts), GeneratorOutput)
    return output.content.strip()
