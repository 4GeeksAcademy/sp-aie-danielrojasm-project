"""`POST /agent/query`: invoca el grafo compilado del agente y traduce su resultado a HTTP.

Convive con `POST /knowledge/query`. No hay lógica de negocio aquí: la recuperación, la generación y el enrutado
viven en el grafo. Si un nodo falla, el cliente recibe un mensaje claro con el `run_id` de la corrida; el tipo de
error, el nodo y el detalle técnico solo van al trace y al log `trackflow.agent`.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from data.process.rag import RagConfigurationError, RagServiceError
from services.api.security import get_current_user
from services.support_agent.models import AgentQueryRequest, AgentQueryResponse
from services.support_agent.runner import AgentRunError, run_agent


router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(get_current_user)])

AGENT_UNAVAILABLE_DETAIL = (
    "El agente de soporte no está disponible ahora mismo. Inténtalo de nuevo en unos minutos "
    "y, si sigue fallando, avisa al equipo técnico con la referencia {run_id}."
)
AGENT_FAILED_DETAIL = (
    "El agente de soporte no pudo responder a esta pregunta. Avisa al equipo técnico con la referencia {run_id}."
)


@router.post(
    "/query",
    response_model=AgentQueryResponse,
    responses={
        422: {"description": "La pregunta está vacía o no es válida."},
        500: {"description": "Un nodo del grafo falló; la respuesta incluye la referencia de la corrida."},
        503: {"description": "Qdrant, la colección o el gateway LLM no están disponibles."},
    },
)
def agent_query(body: AgentQueryRequest) -> AgentQueryResponse:
    try:
        run = run_agent(body.question)
    except AgentRunError as error:
        if isinstance(error.__cause__, (RagServiceError, RagConfigurationError)):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, AGENT_UNAVAILABLE_DETAIL.format(run_id=error.run_id)
            ) from error
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, AGENT_FAILED_DETAIL.format(run_id=error.run_id)
        ) from error
    if "error" in run.state:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, run.state["error"])
    return AgentQueryResponse(answer=run.state["answer"], run_id=run.run_id)
