"""Contrato de `POST /knowledge/query` (base de conocimiento comercial, RAG).

La respuesta solo lleva el texto generado por el modelo: ni chunks, ni puntuaciones, ni IDs de Qdrant.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


MAX_QUESTION_LENGTH = 1000


class KnowledgeQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=MAX_QUESTION_LENGTH)
    ] = Field(description="Pregunta del account manager en lenguaje natural.")


class KnowledgeQueryResponse(BaseModel):
    answer: str = Field(description="Respuesta generada por el modelo a partir de los documentos recuperados.")
