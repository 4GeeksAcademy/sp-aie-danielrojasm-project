"""Tool `get_ticket`: estado de un ticket del gestor de incidencias, en tiempo real, a través del servidor MCP.

- **Único camino al gestor:** el agente no llama a la API de incidencias. Carga la tool `get_ticket_status` del
  servidor MCP de TrackFlow (`mcps/trackflow_tools`, `MCP_SERVER_URL`) con `langchain-mcp-adapters` y la invoca.
- **Auth:** token OAuth `client_credentials` del cliente `support-agent` (`AGENT_OAUTH_CLIENT_ID`,
  `KEYCLOAK_AGENT_CLIENT_SECRET`) emitido por el issuer `MCP_OAUTH_ISSUER`. Ese cliente solo tiene el scope
  `incidents:read`: aunque lo intentara, el servidor le rechazaría crear tickets o cambiar su estado.
- **Timeout:** `INCIDENTS_TIMEOUT_SECONDS` (4 s) para el token y para la llamada MCP.
- **Sin excepciones hacia el grafo:** cualquier fallo se devuelve como `outcome` (`not_found`, `timeout`,
  `unavailable`) para que el grafo tome la ruta de fallback; el detalle técnico va al log `trackflow.agent`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Literal

import httpx
from langchain_core.tools import BaseTool, ToolException
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError

from packages.shared.incidents.domain import Branch, IncidentCategory, IncidentOrigin, IncidentStatus


logger = logging.getLogger("trackflow.agent")

INCIDENTS_TIMEOUT_SECONDS = 4.0
DEFAULT_MCP_SERVER_URL = "http://127.0.0.1:8001/mcp"
MCP_SERVER_NAME = "trackflow"
MCP_TICKET_TOOL = "get_ticket_status"
MCP_TICKET_SCOPE = "incidents:read"

STATUS_LABELS = {
    IncidentStatus.OPEN: "abierta",
    IncidentStatus.IN_PROGRESS: "en curso",
    IncidentStatus.RESOLVED: "resuelta",
    IncidentStatus.DISCARDED: "descartada",
}


class TicketQuery(BaseModel):
    """Entrada de la tool."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: PositiveInt


class Ticket(BaseModel):
    """Los campos del ticket que devuelve `get_ticket_status` (sin `reported_by`, que es un email interno)."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    description: str
    status: IncidentStatus
    category: IncidentCategory
    origin: IncidentOrigin
    branch: Branch
    created_at: datetime
    updated_at: datetime


class TicketLookup(BaseModel):
    """Salida de la tool: el ticket si se encontró o el motivo por el que no se pudo confirmar."""

    ticket_id: int
    outcome: Literal["found", "not_found", "timeout", "unavailable"]
    ticket: Ticket | None = Field(default=None, description="Solo cuando outcome = found.")


class McpAccessError(RuntimeError):
    """No hay credenciales o el proveedor OAuth no emitió el token del agente."""


def get_ticket(query: TicketQuery) -> TicketLookup:
    # El grafo es síncrono y se ejecuta fuera del event loop (endpoint `def` de FastAPI, scripts y tests).
    return asyncio.run(get_ticket_async(query))


async def get_ticket_async(query: TicketQuery) -> TicketLookup:
    ticket_id = query.ticket_id
    try:
        tool = await load_ticket_tool()
        content = await asyncio.wait_for(tool.ainvoke({"ticket_id": ticket_id}), INCIDENTS_TIMEOUT_SECONDS)
    except McpAccessError as error:
        logger.error("get_ticket ticket_id=%d sin token para el servidor MCP: %s", ticket_id, error)
        return TicketLookup(ticket_id=ticket_id, outcome="unavailable")
    except ToolException as error:
        code = _error_code(error)
        if code == "NOT_FOUND":
            logger.info("get_ticket ticket_id=%d no existe", ticket_id)
            return TicketLookup(ticket_id=ticket_id, outcome="not_found")
        logger.error("get_ticket ticket_id=%d el servidor MCP respondió %s", ticket_id, code)
        return TicketLookup(ticket_id=ticket_id, outcome="unavailable")
    except Exception as error:  # noqa: BLE001 - transporte MCP: red, HTTP o grupos de excepciones de anyio
        if _is_timeout(error):
            logger.error("get_ticket ticket_id=%d timeout tras %.0f s", ticket_id, INCIDENTS_TIMEOUT_SECONDS)
            return TicketLookup(ticket_id=ticket_id, outcome="timeout")
        logger.error("get_ticket ticket_id=%d servidor MCP no disponible: %s", ticket_id, type(error).__name__)
        return TicketLookup(ticket_id=ticket_id, outcome="unavailable")
    try:
        ticket = Ticket.model_validate_json(_text(content))
    except (ValueError, ValidationError):
        logger.error("get_ticket ticket_id=%d respuesta del servidor MCP con formato inesperado", ticket_id)
        return TicketLookup(ticket_id=ticket_id, outcome="unavailable")
    logger.info("get_ticket ticket_id=%d status=%s via=mcp", ticket_id, ticket.status.value)
    return TicketLookup(ticket_id=ticket_id, outcome="found", ticket=ticket)


async def load_ticket_tool() -> BaseTool:
    """La tool `get_ticket_status` del servidor MCP; el agente no carga ninguna otra (mínimo privilegio)."""
    client = MultiServerMCPClient(
        {
            MCP_SERVER_NAME: {
                "transport": "streamable_http",
                "url": mcp_server_url(),
                "headers": {"Authorization": f"Bearer {await fetch_access_token()}"},
                "timeout": INCIDENTS_TIMEOUT_SECONDS,
            }
        },
        handle_tool_errors=False,
    )
    tools = await client.get_tools(server_name=MCP_SERVER_NAME)
    for tool in tools:
        if tool.name == MCP_TICKET_TOOL:
            return tool
    raise McpAccessError(f"el servidor MCP no expone la tool {MCP_TICKET_TOOL}")


async def fetch_access_token() -> str:
    issuer = os.getenv("MCP_OAUTH_ISSUER")
    client_id = os.getenv("AGENT_OAUTH_CLIENT_ID")
    secret = os.getenv("KEYCLOAK_AGENT_CLIENT_SECRET")
    if not (issuer and client_id and secret):
        raise McpAccessError("faltan MCP_OAUTH_ISSUER, AGENT_OAUTH_CLIENT_ID o KEYCLOAK_AGENT_CLIENT_SECRET")
    async with httpx.AsyncClient(timeout=INCIDENTS_TIMEOUT_SECONDS) as http:
        discovery = await http.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration")
        discovery.raise_for_status()
        response = await http.post(
            discovery.json()["token_endpoint"],
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": secret,
                "scope": MCP_TICKET_SCOPE,
            },
        )
    if response.status_code != 200:
        raise McpAccessError(f"el proveedor OAuth respondió {response.status_code}")
    return response.json()["access_token"]


def mcp_server_url() -> str:
    return os.getenv("MCP_SERVER_URL") or DEFAULT_MCP_SERVER_URL


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if isinstance(block, dict))


def _error_code(error: ToolException) -> str:
    """Código del error de la tool (`{"code", "message"}` del servidor MCP)."""
    try:
        return str(json.loads(_text(error.args[0] if error.args else ""))["code"])
    except (ValueError, KeyError, TypeError):
        return "UNKNOWN"


def _is_timeout(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return True
    if isinstance(error, BaseExceptionGroup):
        return any(_is_timeout(inner) for inner in error.exceptions)
    return error.__cause__ is not None and _is_timeout(error.__cause__)


def ticket_fragment(ticket: Ticket) -> dict[str, str | int]:
    """El ticket como fragmento de contexto para `generate_answer()` (mismas claves que los payloads del RAG)."""
    text = (
        f"Ticket {ticket.id} del gestor de incidencias (dato en tiempo real): \"{ticket.title}\". "
        f"Estado: {STATUS_LABELS[ticket.status]} ({ticket.status.value}). Categoría: {ticket.category.value}. "
        f"Origen: {ticket.origin.value}. Sede: {ticket.branch.value}. "
        f"Creado: {ticket.created_at.isoformat()}. Última actualización: {ticket.updated_at.isoformat()}. "
        f"Descripción: {ticket.description}"
    )
    return {
        "company": "trackflow",
        "source_document": "incident-manager",
        "section": f"Gestor de incidencias › Ticket {ticket.id}",
        "language": "es",
        "chunk_index": ticket.id,
        "text": text,
    }
