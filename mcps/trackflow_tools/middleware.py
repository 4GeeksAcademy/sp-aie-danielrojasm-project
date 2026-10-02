"""Middleware de las llamadas a tools: scope de cada tool, errores con código y un log por invocación.

El token ya lo validó MCP Auth (firma, issuer, audience, expiración) y dejó su `AuthInfo` en `AUTH_CONTEXT`.
Aquí solo se decide si ese token puede usar la tool pedida (`TOOL_SCOPES`) y se registra en `trackflow.mcp`:
`tool_call tool=… client=… subject=… result=ok|<CÓDIGO> duration_ms=…`.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar

from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types as mt
from mcpauth.types import AuthInfo
from pydantic import ValidationError as PydanticValidationError

from mcps.trackflow_tools.errors import ErrorCode, ToolFailure
from mcps.trackflow_tools.tools import TOOL_SCOPES


logger = logging.getLogger("trackflow.mcp")

AUTH_CONTEXT: ContextVar[AuthInfo | None] = ContextVar("trackflow_mcp_auth", default=None)


class ToolAccessMiddleware(Middleware):
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool = context.message.name
        auth = AUTH_CONTEXT.get()
        client = (auth.client_id if auth else None) or "-"
        subject = auth.subject if auth else "-"
        started = time.perf_counter()
        try:
            _check_scope(tool, auth)
            result = await call_next(context)
            outcome = "ok"
        except ToolFailure as failure:
            result, outcome = failure.to_result(), failure.code.value
        except ToolError as error:
            # FastMCP envuelve en ToolError lo que lanza la tool; el fallo controlado va en `__cause__`.
            if not isinstance(error.__cause__, ToolFailure):
                logger.info("tool_call tool=%s client=%s subject=%s result=error", tool, client, subject)
                raise
            result, outcome = error.__cause__.to_result(), error.__cause__.code.value
        except ValidationError as error:
            failure = _validation_failure(error)
            result, outcome = failure.to_result(), failure.code.value
        logger.info(
            "tool_call tool=%s client=%s subject=%s result=%s duration_ms=%.0f",
            tool,
            client,
            subject,
            outcome,
            (time.perf_counter() - started) * 1000,
        )
        return result


def _check_scope(tool: str, auth: AuthInfo | None) -> None:
    required = TOOL_SCOPES.get(tool)
    if required is None:
        return  # Tool inexistente: FastMCP responde "Unknown tool".
    granted = auth.scopes if auth else []
    if required not in granted:
        raise ToolFailure(
            ErrorCode.INSUFFICIENT_SCOPE,
            f"El token no tiene el scope '{required}' que exige la tool '{tool}'. "
            f"Scopes del token: {', '.join(granted) or 'ninguno'}.",
        )


def _validation_failure(error: ValidationError) -> ToolFailure:
    cause = error.__cause__
    errors = []
    if isinstance(cause, PydanticValidationError):
        errors = [
            {"field": ".".join(str(part) for part in item["loc"]) or "arguments", "message": item["msg"]}
            for item in cause.errors()
        ]
    return ToolFailure(ErrorCode.VALIDATION_ERROR, "Los argumentos no cumplen el esquema de la tool.", errors)
