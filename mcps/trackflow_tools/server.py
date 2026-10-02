"""App ASGI del servidor MCP: FastMCP sobre Streamable HTTP, protegido por MCP Auth como resource server.

- `GET /.well-known/oauth-protected-resource/mcp`: Protected Resource Metadata (RFC 9728) con el issuer de
  Keycloak y los scopes. Es pública: un cliente la necesita para saber dónde pedir el token.
- `/mcp`: el endpoint MCP (`initialize`, `tools/list`, `tools/call`…). Toda petición pasa antes por el middleware
  bearer de MCP Auth: sin token válido para la audiencia `trackflow-mcp` responde 401 y no llega a FastMCP.

La auth integrada de FastMCP no se usa.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP
from mcpauth import MCPAuth
from mcpauth.config import AuthServerType
from mcpauth.types import ResourceServerConfig, ResourceServerMetadata
from mcpauth.utils import fetch_server_config
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount

from mcps.trackflow_tools.middleware import AUTH_CONTEXT, ToolAccessMiddleware
from mcps.trackflow_tools.tools import SCOPES_SUPPORTED, register_tools


AUDIENCE = "trackflow-mcp"
MCP_PATH = "/mcp"

INSTRUCTIONS = (
    "Herramientas de TrackFlow para el gestor de incidencias (crear tickets, cambiar su estado por el ciclo de vida "
    "y consultarlos) y para consultar el inventario de los almacenes LA y ZGZ en modo solo lectura. Cada tool indica "
    "el scope OAuth que exige. Los errores devuelven JSON {code, message, errors?}; códigos: INSUFFICIENT_SCOPE, "
    "INVENTORY_READ_ONLY, VALIDATION_ERROR, NOT_FOUND, UPSTREAM_UNAVAILABLE."
)


class ConfigError(RuntimeError):
    """Falta una variable de entorno obligatoria."""


def build_mcp() -> FastMCP:
    mcp = FastMCP(name="trackflow-tools", instructions=INSTRUCTIONS)
    register_tools(mcp)
    mcp.add_middleware(ToolAccessMiddleware())
    return mcp


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"Falta la variable {name} en el .env raíz.")
    return value


def create_app() -> Starlette:
    issuer = required_env("MCP_OAUTH_ISSUER")
    resource = required_env("MCP_RESOURCE_URL")
    required_env("MCP_SERVICE_USER_ID")
    required_env("JWT_SECRET_KEY")

    mcp_auth = MCPAuth(
        protected_resources=ResourceServerConfig(
            metadata=ResourceServerMetadata(
                resource=resource,
                # Descarga la configuración OIDC del issuer (JWKS incluido); si no responde, el proceso no arranca.
                authorization_servers=[fetch_server_config(issuer, AuthServerType.OIDC)],
                scopes_supported=SCOPES_SUPPORTED,
                resource_name="TrackFlow MCP tools",
            )
        ),
        context_var=AUTH_CONTEXT,
    )
    bearer = mcp_auth.bearer_auth_middleware("jwt", resource=resource, audience=AUDIENCE)

    # Stateless: cada petición HTTP es independiente, así el `AuthInfo` que deja MCP Auth en el contexto es el de
    # esa misma petición y el servidor atiende a varios clientes remotos sin sesiones pegajosas.
    mcp_app = build_mcp().http_app(
        path=MCP_PATH, stateless_http=True, json_response=True, middleware=[Middleware(bearer)]
    )
    return Starlette(
        routes=[*mcp_auth.resource_metadata_router().routes, Mount("/", app=mcp_app)],
        lifespan=mcp_app.lifespan,
    )
