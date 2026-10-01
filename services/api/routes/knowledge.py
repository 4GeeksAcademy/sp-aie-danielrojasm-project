"""`POST /knowledge/query`: asistente comercial sobre la base de conocimiento de TrackFlow (RAG).

Solo delega en `data.pipelines.rag.query()`: la recuperación y la generación no se duplican aquí.
Sin Qdrant, sin colección indexada o sin gateway LLM responde 503 con un mensaje accionable;
el detalle técnico queda en el log `trackflow.rag`.
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, status

from data.pipelines.rag import query
from data.process.rag import RagConfigurationError, RagServiceError
from services.api.knowledge_models import KnowledgeQueryRequest, KnowledgeQueryResponse
from services.api.security import get_current_user


logger = logging.getLogger("trackflow.rag")

router = APIRouter(prefix="/knowledge", tags=["knowledge"], dependencies=[Depends(get_current_user)])

KNOWLEDGE_UNAVAILABLE_DETAIL = (
    "El asistente comercial no está disponible ahora mismo. Inténtalo de nuevo en unos minutos "
    "y, si sigue fallando, avisa al equipo técnico."
)


@router.post(
    "/query",
    response_model=KnowledgeQueryResponse,
    responses={503: {"description": "Qdrant, la colección o el gateway LLM no están disponibles."}},
)
def knowledge_query(body: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
    started = time.perf_counter()
    try:
        answer = query(body.question)
    except RagConfigurationError as error:
        logger.error("RAG sin configurar: %s", error)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, KNOWLEDGE_UNAVAILABLE_DETAIL) from error
    except RagServiceError as error:
        logger.error("RAG no disponible: %s", error)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, KNOWLEDGE_UNAVAILABLE_DETAIL) from error
    logger.info(
        "knowledge_query question_chars=%d answer_chars=%d duration_ms=%.0f",
        len(body.question),
        len(answer),
        (time.perf_counter() - started) * 1000,
    )
    return KnowledgeQueryResponse(answer=answer)
