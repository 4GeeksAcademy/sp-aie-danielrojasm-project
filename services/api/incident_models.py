from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from packages.shared.incidents.domain import (
    TITLE_MAX_LENGTH,
    Branch,
    IncidentCategory,
    IncidentOrigin,
    IncidentStatus,
)


Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX_LENGTH),
]
Description = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
]


class IncidentCreate(BaseModel):
    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    title: Title
    description: Description
    category: IncidentCategory
    origin: IncidentOrigin
    branch: Branch
    # Las incidencias nuevas siempre empiezan abiertas; se acepta el campo
    # para que el formulario pueda enviarlo, pero se valida en la ruta.
    status: IncidentStatus = IncidentStatus.OPEN


class Incident(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: int
    title: str
    description: str
    category: IncidentCategory
    status: IncidentStatus
    origin: IncidentOrigin
    branch: Branch
    reported_by: str | None = None
    created_at: datetime
    updated_at: datetime


class IncidentStatusUpdate(BaseModel):
    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    status: IncidentStatus


class IncidentSummary(BaseModel):
    total: int
    by_status: dict[IncidentStatus, int]
    by_category: dict[IncidentCategory, int]
    by_origin: dict[IncidentOrigin, int]
    by_branch: dict[Branch, int]


class FieldError(BaseModel):
    field: str
    message: str


class ValidationErrorResponse(BaseModel):
    detail: str
    errors: list[FieldError] = Field(default_factory=list)
