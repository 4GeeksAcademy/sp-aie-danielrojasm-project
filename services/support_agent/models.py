"""Contrato de `POST /agent/query`.

La pregunta vacía no se rechaza aquí: el grafo la enruta a `reject_question` y queda en el trace.
"""

from pydantic import BaseModel, ConfigDict, Field

from services.api.knowledge_models import MAX_QUESTION_LENGTH


class AgentQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(max_length=MAX_QUESTION_LENGTH, description="Pregunta del account manager en lenguaje natural.")


class AgentQueryResponse(BaseModel):
    answer: str = Field(description="Respuesta del agente, anclada en la base de conocimiento comercial.")
    run_id: str = Field(description="Identificador de la corrida: nombre del trace en AGENT_TRACE_DIR.")
