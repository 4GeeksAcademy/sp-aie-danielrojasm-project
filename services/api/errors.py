"""Respuestas de error de la API: mensajes legibles y sin datos del cliente.

La respuesta de validación por defecto de FastAPI incluye ``input`` (el valor
enviado, p. ej. una contraseña) y ``ctx``, y sus mensajes son técnicos y en
inglés. Estas utilidades construyen la versión saneada.
"""

from typing import Any

from fastapi import status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


INTERNAL_ERROR_DETAIL = "Se produjo un error interno. Inténtalo de nuevo en unos minutos."
VALIDATION_DETAIL = "La solicitud contiene datos no válidos."
_LOCATION_PREFIXES = ("body", "query", "path", "header", "cookie")


def field_name(location: tuple[Any, ...]) -> str:
    names = [str(part) for part in location if part not in _LOCATION_PREFIXES]
    return names[-1] if names else "body"


def validation_message(error: dict[str, Any]) -> str:
    """Traduce un error de Pydantic a un mensaje en español, sin el valor recibido."""
    error_type = error.get("type", "")
    context = error.get("ctx") or {}
    field = field_name(tuple(error.get("loc", ())))
    if error_type == "missing":
        return "Este campo es obligatorio."
    if error_type == "string_too_short":
        minimum = context.get("min_length", 1)
        if minimum <= 1:
            return "Este campo no puede estar vacío."
        return f"Debe tener al menos {minimum} caracteres."
    if error_type == "string_too_long":
        return f"Admite como máximo {context.get('max_length')} caracteres."
    if error_type == "enum":
        return f"Valor no permitido. Valores válidos: {context.get('expected')}."
    if error_type in ("too_short", "list_type") and field == "categories":
        return "Selecciona al menos una categoría."
    if error_type in ("greater_than", "greater_than_equal"):
        return f"Debe ser mayor que {context.get('gt', context.get('ge'))}."
    if error_type == "string_type":
        return "Debe ser un texto."
    if error_type in ("int_parsing", "int_type"):
        return "Debe ser un número entero."
    if error_type in ("float_parsing", "float_type"):
        return "Debe ser un número."
    if error_type == "bool_parsing":
        return "Debe ser verdadero o falso."
    if error_type == "extra_forbidden":
        return "Este campo no se admite en la solicitud."
    if error_type == "json_invalid":
        return "El cuerpo de la solicitud no es un JSON válido."
    if error_type in ("model_attributes_type", "dict_type"):
        return "El cuerpo de la solicitud debe ser un objeto JSON."
    if error_type == "value_error":
        if "email" in field:
            return "Introduce un email válido."
        # Los validadores propios (p. ej. moneda por país) ya lanzan mensajes en
        # español; Pydantic solo les antepone "Value error, ".
        message = str(error.get("msg", ""))
        return message.removeprefix("Value error, ") or "Valor no válido."
    return "Valor no válido."


def sanitized_validation_errors(error: RequestValidationError) -> list[dict[str, Any]]:
    """Formato compatible con FastAPI (``loc``, ``msg``, ``type``) sin ``input`` ni ``ctx``."""
    return [
        {
            "loc": list(item.get("loc", ())),
            "msg": validation_message(item),
            "type": item.get("type", "value_error"),
        }
        for item in error.errors()
    ]


def unprocessable_response(error: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": sanitized_validation_errors(error)},
    )


def internal_error_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": INTERNAL_ERROR_DETAIL},
    )
