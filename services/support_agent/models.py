"""Contrato de `POST /agent/query`.

La pregunta vacía no se rechaza aquí: el grafo la enruta a `reject_question` y queda en el trace.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.api.knowledge_models import MAX_QUESTION_LENGTH


class AgentQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(max_length=MAX_QUESTION_LENGTH, description="Pregunta del account manager en lenguaje natural.")
    conversation_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{8,64}$",
        description="Conversación del turno anterior. Sin ella empieza una conversación nueva.",
    )


class MemoryProposalRead(BaseModel):
    proposal_id: str
    category: Literal["carrier_rule", "incident_context", "client_preference"]
    subject: str
    fact: str = Field(description="Lo que el agente recordaría si el usuario lo aprueba en su próximo mensaje.")
    expires_at: datetime = Field(description="Sin respuesta antes de esta hora, la propuesta se descarta.")


class MemoryDecisionRead(BaseModel):
    proposal_id: str
    outcome: Literal["approved", "edited", "rejected", "discarded"]
    fact: str | None = Field(description="Lo que se guardó (solo si se aprobó o editó).")


class AgentQueryResponse(BaseModel):
    answer: str = Field(description="Respuesta del agente, anclada en la base de conocimiento comercial.")
    run_id: str = Field(description="Identificador de la corrida: nombre del trace en AGENT_TRACE_DIR.")
    conversation_id: str = Field(description="Conversación a enviar en el siguiente turno.")
    memory_proposal: MemoryProposalRead | None = Field(
        default=None, description="Propuesta de memoria que espera la decisión del usuario, si el agente hizo una."
    )
    memory_decision: MemoryDecisionRead | None = Field(
        default=None, description="Decisión aplicada en este turno sobre la propuesta anterior, si la había."
    )


class GuardrailSummary(BaseModel):
    since: datetime = Field(description="Inicio de la ventana: arranque del proceso de la API.")
    total: int = Field(description="Activaciones de guardrails (bloqueos, redirecciones, limpiezas y correcciones).")
    by_guardrail: dict[str, int] = Field(description="Por capa: input_guard, external_content_isolation, output_guard.")
    by_failure_type: dict[str, int] = Field(description="Por tipo de fallo: structural, content, security.")
    by_action: dict[str, int] = Field(description="Por acción: block, redirect, constrain, sanitize, redact, repair.")
