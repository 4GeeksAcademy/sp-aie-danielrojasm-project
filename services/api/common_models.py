"""Schemas de respuesta compartidos por varios routers de la API."""

from pydantic import BaseModel


class MessageResponse(BaseModel):
    """Confirmación genérica: el cliente solo necesita saber que la operación terminó."""

    message: str


class HealthResponse(BaseModel):
    service: str
    status: str
