"""Contratos de la memoria del agente.

Los nombres en español con alias (`categoria`, `hecho`, `decision`, `confianza`…) son las claves del JSON que
devuelve el modelo; el resto del código usa los nombres en inglés.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MemoryCategory = Literal["carrier_rule", "incident_context", "client_preference"]
DecisionLabel = Literal["approve", "reject", "edit", "unrelated"]
DecisionOutcome = Literal["approved", "edited", "rejected", "discarded"]


class MemoryDraft(BaseModel):
    """`propuesta_memoria` tal como la devuelve el modelo, antes de pasar por `policy.build_proposal`."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    category: str = Field(alias="categoria")
    fact: str = Field(alias="hecho", min_length=1)
    reason: str = Field(default="", alias="motivo")
    user_quote: str = Field(default="", alias="cita_usuario")
    carrier: str | None = Field(default=None, alias="transportista")
    country: str | None = Field(default=None, alias="pais")
    zone: str | None = Field(default=None, alias="zona")
    client: str | None = Field(default=None, alias="cliente")


class MemoryProposal(BaseModel):
    """Propuesta validada que espera la decisión del usuario (como mucho una por usuario)."""

    proposal_id: str
    category: MemoryCategory
    subject_key: str
    subject: str
    keywords: list[str]
    fact: str
    reason: str
    user_id: str
    conversation_id: str
    run_id: str
    # Mensaje que originó la propuesta, ya redactado (`policy.redact`).
    source_message: str
    proposed_at: datetime
    expires_at: datetime


class MemoryFact(BaseModel):
    fact: str
    proposal_id: str
    approved_by: str
    approved_at: datetime
    expires_at: datetime


class MemoryEntry(BaseModel):
    """Entrada consolidada: una por transportista + país, zona + país o cliente B2B, con sus hechos aprobados."""

    subject_key: str
    category: MemoryCategory
    subject: str
    keywords: list[str]
    facts: list[MemoryFact]
    updated_at: datetime


class DecisionClassification(BaseModel):
    """Etiqueta estructurada del mensaje del usuario frente a la propuesta pendiente."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    decision: DecisionLabel
    confidence: float = Field(alias="confianza", ge=0, le=1)
    edited_fact: str | None = Field(default=None, alias="hecho_editado")
    follow_up: str = Field(default="", alias="resto_del_mensaje")
    decided_by: Literal["llm", "default"] = "llm"


class Resolution(BaseModel):
    """Qué se hace con la propuesta pendiente y qué parte del mensaje sigue siendo una pregunta."""

    outcome: DecisionOutcome
    reason: str
    fact: str | None = None
    follow_up: str = ""
