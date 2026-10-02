"""`uv run --env-file .env python -m mcps.trackflow_tools` (puerto `MCP_PORT`, 8001 por defecto).

Códigos de salida: 0 parada normal; 2 falta configuración; 3 el proveedor OAuth (`MCP_OAUTH_ISSUER`) no responde.
"""

from __future__ import annotations

import logging
import os
import sys

import uvicorn
from mcpauth.exceptions import MCPAuthAuthServerException, MCPAuthConfigException

from mcps.trackflow_tools.errors import EXIT_AUTH_SERVER_UNREACHABLE, EXIT_CONFIG_ERROR
from mcps.trackflow_tools.server import ConfigError, create_app


logger = logging.getLogger("trackflow.mcp")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        app = create_app()
    except ConfigError as error:
        logger.error("%s", error)
        return EXIT_CONFIG_ERROR
    except (MCPAuthAuthServerException, MCPAuthConfigException) as error:
        logger.error("No se pudo leer la configuración OIDC de MCP_OAUTH_ISSUER: %s", error)
        return EXIT_AUTH_SERVER_UNREACHABLE
    uvicorn.run(app, host=os.getenv("MCP_HOST", "0.0.0.0"), port=int(os.getenv("MCP_PORT", "8001")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
