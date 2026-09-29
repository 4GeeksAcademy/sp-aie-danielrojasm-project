import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from packages.shared.incidents.domain import (
    STATUS_TRANSITIONS,
    Branch,
    IncidentCategory,
    IncidentOrigin,
    IncidentStatus,
    can_transition,
)
from services.api.auth_models import User
from services.api.database import INCIDENTS_TABLE, get_incidents_db
from services.api.incident_models import (
    FieldError,
    Incident,
    IncidentCreate,
    IncidentStatusUpdate,
    IncidentSummary,
    ValidationErrorResponse,
)
from services.api.security import get_current_user


logger = logging.getLogger("trackflow.incidents")

INCIDENTS_PREFIX = "/api/incidents"
VALIDATION_DETAIL = "La solicitud contiene datos no válidos."

router = APIRouter(
    prefix=INCIDENTS_PREFIX,
    tags=["incidents"],
    dependencies=[Depends(get_current_user)],
    responses={400: {"model": ValidationErrorResponse}},
)


class IncidentValidationError(Exception):
    """Business-rule violation reported as 400 with the offending field."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def validation_error_response(errors: list[FieldError]) -> JSONResponse:
    body = ValidationErrorResponse(detail=VALIDATION_DETAIL, errors=errors)
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=body.model_dump())


def _field_name(location: tuple[Any, ...]) -> str:
    names = [str(part) for part in location if part not in ("body", "query", "path")]
    return names[-1] if names else "body"


def _error_message(error: dict[str, Any]) -> str:
    error_type = error.get("type", "")
    context = error.get("ctx") or {}
    if error_type == "missing":
        return "Este campo es obligatorio."
    if error_type == "string_too_short":
        return "Este campo no puede estar vacío."
    if error_type == "string_too_long":
        return f"Admite como máximo {context.get('max_length')} caracteres."
    if error_type == "enum":
        return f"Valor no permitido. Valores válidos: {context.get('expected')}."
    if error_type == "string_type":
        return "Debe ser un texto."
    if error_type == "int_parsing":
        return "Debe ser un número entero."
    if error_type == "extra_forbidden":
        return "Este campo no se admite en la solicitud."
    if error_type == "json_invalid":
        return "El cuerpo de la solicitud no es un JSON válido."
    if error_type in ("model_attributes_type", "dict_type"):
        return "El cuerpo de la solicitud debe ser un objeto JSON."
    return "Valor no válido."


async def handle_request_validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    """400 with one entry per field. Only registered for incident routes."""
    errors = [
        FieldError(field=_field_name(tuple(item.get("loc", ()))), message=_error_message(item))
        for item in error.errors()
    ]
    logger.info(
        "Solicitud rechazada %s %s: %s",
        request.method,
        request.url.path,
        [item.field for item in errors],
    )
    return validation_error_response(errors)


async def handle_incident_validation_error(
    request: Request, error: IncidentValidationError
) -> JSONResponse:
    logger.info(
        "Regla de negocio incumplida %s %s: %s",
        request.method,
        request.url.path,
        error.field,
    )
    return validation_error_response([FieldError(field=error.field, message=error.message)])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _incident_from_document(document: Any) -> Incident:
    return Incident(id=int(document.doc_id), **dict(document))


def _get_document(table: Any, incident_id: int) -> Any:
    document = table.get(doc_id=incident_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Incidencia no encontrada.")
    return document


@router.post("", response_model=Incident, status_code=status.HTTP_201_CREATED)
def create_incident(
    payload: IncidentCreate,
    current_user: User = Depends(get_current_user),
) -> Incident:
    if payload.status != IncidentStatus.OPEN.value:
        raise IncidentValidationError(
            "status",
            "Las incidencias nuevas se registran como abiertas (open).",
        )
    timestamp = _now()
    with get_incidents_db() as db:
        table = db.table(INCIDENTS_TABLE)
        document_id = table.insert(
            {
                **payload.model_dump(),
                "reported_by": current_user.email,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
        document = table.get(doc_id=document_id)
    logger.info(
        "Incidencia %s creada por %s (origen=%s, sede=%s, categoría=%s)",
        document_id,
        current_user.id,
        payload.origin,
        payload.branch,
        payload.category,
    )
    return _incident_from_document(document)


@router.get("", response_model=list[Incident])
def list_incidents(
    status_filter: IncidentStatus | None = Query(default=None, alias="status"),
    origin: IncidentOrigin | None = None,
    branch: Branch | None = None,
    category: IncidentCategory | None = None,
) -> list[Incident]:
    filters = {
        "status": status_filter,
        "origin": origin,
        "branch": branch,
        "category": category,
    }
    active = {key: value.value for key, value in filters.items() if value is not None}
    with get_incidents_db() as db:
        documents = db.table(INCIDENTS_TABLE).all()
    incidents = [
        _incident_from_document(document)
        for document in documents
        if all(document.get(key) == value for key, value in active.items())
    ]
    return sorted(incidents, key=lambda item: (item.created_at, item.id), reverse=True)


@router.get("/summary", response_model=IncidentSummary)
def incidents_summary() -> IncidentSummary:
    with get_incidents_db() as db:
        documents = db.table(INCIDENTS_TABLE).all()

    def totals(field: str, values: type[Any]) -> dict[Any, int]:
        counts = Counter(document.get(field) for document in documents)
        return {value: counts[value.value] for value in values}

    return IncidentSummary(
        total=len(documents),
        by_status=totals("status", IncidentStatus),
        by_category=totals("category", IncidentCategory),
        by_origin=totals("origin", IncidentOrigin),
        by_branch=totals("branch", Branch),
    )


@router.get("/{incident_id}", response_model=Incident)
def get_incident(incident_id: int) -> Incident:
    with get_incidents_db() as db:
        document = _get_document(db.table(INCIDENTS_TABLE), incident_id)
    return _incident_from_document(document)


@router.patch("/{incident_id}/status", response_model=Incident)
def update_incident_status(
    incident_id: int,
    payload: IncidentStatusUpdate,
    current_user: User = Depends(get_current_user),
) -> Incident:
    target = IncidentStatus(payload.status)
    with get_incidents_db() as db:
        table = db.table(INCIDENTS_TABLE)
        current = IncidentStatus(_get_document(table, incident_id)["status"])
        if not can_transition(current, target):
            allowed = sorted(value.value for value in STATUS_TRANSITIONS[current])
            message = (
                f"No se puede pasar de '{current.value}' a '{target.value}'. "
                + (
                    f"Transiciones permitidas: {', '.join(allowed)}."
                    if allowed
                    else f"El estado '{current.value}' es final."
                )
            )
            raise IncidentValidationError("status", message)
        table.update({"status": target.value, "updated_at": _now()}, doc_ids=[incident_id])
        document = table.get(doc_id=incident_id)
    logger.info(
        "Incidencia %s: %s -> %s por %s",
        incident_id,
        current.value,
        target.value,
        current_user.id,
    )
    return _incident_from_document(document)


def is_incidents_path(request: Request) -> bool:
    return request.url.path.startswith(INCIDENTS_PREFIX)

