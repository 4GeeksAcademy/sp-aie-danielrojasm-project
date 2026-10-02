"""Servidor MCP real (`mcps/trackflow_tools`) en un hilo, con un proveedor OAuth de prueba.

MCP Auth verifica la firma de verdad: los tokens se firman con una clave RSA propia del test y su JWKS sustituye a la
descarga del issuer, así que no hacen falta Keycloak ni red. La API de TrackFlow llega por el `httpx` transport que
pasa cada test (la app FastAPI real o un `MockTransport`).
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm
from mcpauth.config import AuthorizationServerMetadata, AuthServerConfig, AuthServerType

from mcps.trackflow_tools import backend, server


ISSUER = "https://auth.test/realms/trackflow"
KEY_ID = "test-key"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWKS = {"keys": [{**json.loads(RSAAlgorithm.to_jwk(SIGNING_KEY.public_key())), "kid": KEY_ID, "alg": "RS256", "use": "sig"}]}
ALL_SCOPES = ["incidents:read", "incidents:write", "inventory:read"]


def issue_token(
    scopes: list[str],
    *,
    client_id: str = "trackflow-operator",
    audience: str = server.AUDIENCE,
    issuer: str = ISSUER,
    expires_in: int = 300,
    key: rsa.RSAPrivateKey = SIGNING_KEY,
) -> str:
    now = int(time.time())
    claims = {
        "iss": issuer,
        "sub": f"service-account-{client_id}",
        "azp": client_id,
        "aud": audience,
        "scope": " ".join(scopes),
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KEY_ID})


def auth_server_config(issuer: str, server_type: AuthServerType) -> AuthServerConfig:
    return AuthServerConfig(
        type=server_type,
        metadata=AuthorizationServerMetadata(
            issuer=ISSUER,
            authorization_endpoint=f"{ISSUER}/protocol/openid-connect/auth",
            token_endpoint=f"{ISSUER}/protocol/openid-connect/token",
            jwks_uri=f"{ISSUER}/protocol/openid-connect/certs",
            response_types_supported=["code"],
        ),
    )


@contextlib.contextmanager
def running_mcp_server(monkeypatch, api_transport: httpx.AsyncBaseTransport, service_user_id: str = "service-user") -> Iterator[str]:
    """Arranca el servidor y devuelve la URL del endpoint MCP (`http://127.0.0.1:<puerto>/mcp`)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}{server.MCP_PATH}"
    monkeypatch.setenv("MCP_OAUTH_ISSUER", ISSUER)
    monkeypatch.setenv("MCP_RESOURCE_URL", url)
    monkeypatch.setenv("MCP_SERVICE_USER_ID", service_user_id)
    monkeypatch.setattr(server, "fetch_server_config", auth_server_config)
    monkeypatch.setattr(PyJWKClient, "fetch_data", lambda self: JWKS)
    monkeypatch.setattr(
        backend,
        "http_client",
        lambda: httpx.AsyncClient(transport=api_transport, base_url="http://api.test", timeout=backend.TIMEOUT_SECONDS),
    )

    uvicorn_server = uvicorn.Server(uvicorn.Config(server.create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not uvicorn_server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("El servidor MCP de prueba no arrancó.")
        time.sleep(0.02)
    try:
        yield url
    finally:
        uvicorn_server.should_exit = True
        thread.join(timeout=10)
