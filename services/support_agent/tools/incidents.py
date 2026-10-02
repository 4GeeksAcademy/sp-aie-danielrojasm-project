"""Tool `get_ticket`: estado de un ticket en el gestor de incidencias (`GET /api/incidents/{id}`), en tiempo real.

- **Solo lectura:** la única petición que hace es un `GET`; nunca crea, cambia ni borra incidencias.
- **Transporte:** HTTP contra la API que ya sirve el gestor (`INCIDENTS_API_URL`, por defecto `http://127.0.0.1:8000`).
- **Auth:** el gestor exige bearer. La tool firma un token de vida corta para la cuenta de servicio
  `AGENT_SERVICE_USER_ID` con el mismo `JWT_SECRET_KEY` de la API; no hay tokens fijos en el código ni en el `.env`.
- **Timeout:** `INCIDENTS_TIMEOUT_SECONDS` (4 s) para conectar y leer.
- **Sin excepciones hacia el grafo:** cualquier fallo se devuelve como `outcome` (`not_found`, `timeout`,
  `unavailable`) para que el grafo tome la ruta de fallback; el detalle técnico va al log `trackflow.agent`.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError

from packages.shared.incidents.domain import Branch, IncidentCategory, IncidentOrigin, IncidentStatus
from services.api.security import create_access_token


logger = logging.getLogger("trackflow.agent")

INCIDENTS_TIMEOUT_SECONDS = 4.0
SERVICE_TOKEN_TTL = timedelta(minutes=5)
DEFAULT_INCIDENTS_API_URL = "http://127.0.0.1:8000"

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
    """Los campos de `GET /api/incidents/{id}` que necesita el agente (sin `reported_by`, que es un email interno)."""

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


def get_ticket(query: TicketQuery, *, client: httpx.Client | None = None) -> TicketLookup:
    ticket_id = query.ticket_id
    service_user = os.getenv("AGENT_SERVICE_USER_ID")
    if not service_user:
        logger.error("get_ticket ticket_id=%d sin AGENT_SERVICE_USER_ID: no hay credenciales para el gestor.", ticket_id)
        return TicketLookup(ticket_id=ticket_id, outcome="unavailable")

    url = f"{incidents_api_url()}/api/incidents/{ticket_id}"
    headers = {"Authorization": f"Bearer {create_access_token(service_user, SERVICE_TOKEN_TTL)}"}
    try:
        if client is None:
            with httpx.Client(timeout=INCIDENTS_TIMEOUT_SECONDS) as own_client:
                response = own_client.get(url, headers=headers)
        else:
            response = client.get(url, headers=headers, timeout=INCIDENTS_TIMEOUT_SECONDS)
    except httpx.TimeoutException:
        logger.error("get_ticket ticket_id=%d timeout tras %.0f s", ticket_id, INCIDENTS_TIMEOUT_SECONDS)
        return TicketLookup(ticket_id=ticket_id, outcome="timeout")
    except httpx.HTTPError as error:
        logger.error("get_ticket ticket_id=%d gestor de incidencias no disponible: %s", ticket_id, type(error).__name__)
        return TicketLookup(ticket_id=ticket_id, outcome="unavailable")

    if response.status_code == 404:
        logger.info("get_ticket ticket_id=%d no existe", ticket_id)
        return TicketLookup(ticket_id=ticket_id, outcome="not_found")
    if response.status_code != 200:
        logger.error("get_ticket ticket_id=%d respuesta %d del gestor", ticket_id, response.status_code)
        return TicketLookup(ticket_id=ticket_id, outcome="unavailable")
    try:
        ticket = Ticket.model_validate(response.json())
    except (ValueError, ValidationError):
        logger.error("get_ticket ticket_id=%d respuesta del gestor con formato inesperado", ticket_id)
        return TicketLookup(ticket_id=ticket_id, outcome="unavailable")
    logger.info("get_ticket ticket_id=%d status=%s", ticket_id, ticket.status.value)
    return TicketLookup(ticket_id=ticket_id, outcome="found", ticket=ticket)


def incidents_api_url() -> str:
    return (os.getenv("INCIDENTS_API_URL") or DEFAULT_INCIDENTS_API_URL).rstrip("/")


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
