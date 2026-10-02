# `mcps/trackflow_tools` — Servidor MCP de herramientas de TrackFlow

Expone como servidor MCP independiente las capacidades que el agente de soporte tenía dentro de su grafo: gestionar
tickets del gestor de incidencias y consultar el inventario (solo lectura). Cualquier cliente MCP con un access token
OAuth válido puede descubrir y usar las tools. El servidor se apoya en la API de TrackFlow (`services/api`); no la
reemplaza ni accede a sus bases de datos.

## Transporte: Streamable HTTP

El servidor lo consumen clientes remotos (el agente, otros equipos o partners y MCP Playground). stdio solo sirve a un
proceso local que lanza el servidor como hijo, y en ese caso no hay petición HTTP ni cabecera `Authorization` en la que
validar un token OAuth. Streamable HTTP permite que MCP Auth actúe como resource server: valida el bearer en cada
petición y publica la Protected Resource Metadata.

El modo es **stateless** (`stateless_http=True`, respuestas JSON): cada petición HTTP se autentica y se resuelve sola,
con su propio token. No hay sesiones que fijar a una réplica, y la identidad que se registra en el log siempre es la del
token de esa petición.

## Arranque

Dos formas, que no conviven porque las dos usan el 8001:

```bash
# Todo en Docker Compose (servicio `mcp`; el agente del contenedor `api` lo usa por nombre de servicio)
docker compose up -d keycloak api mcp

# O el servidor en el host, con Keycloak y la API en Compose
docker compose up -d keycloak api
uv run --env-file .env python -m mcps.trackflow_tools   # http://0.0.0.0:8001/mcp
```

En Compose, el servicio `mcp` (`mcps/trackflow_tools/Dockerfile`, contexto en la raíz porque importa `services.api` y
`packages.shared`) recibe el `.env` entero y sobrescribe dos variables: `MCP_OAUTH_ISSUER` con
`DOCKER_MCP_OAUTH_ISSUER` (`http://keycloak:8080/realms/trackflow`) y `TRACKFLOW_API_URL` con
`TRACKFLOW_API_INTERNAL_URL` (`http://api:8000`). El código llega por bind mount; tras cambiar las dependencias,
`docker compose build mcp`.

**El issuer es el mismo dentro y fuera de Compose.** Keycloak corre con `KC_HOSTNAME=KEYCLOAK_URL`
(`http://127.0.0.1:8080`) y `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`: todos los tokens llevan
`iss=http://127.0.0.1:8080/realms/trackflow`, pero el discovery devuelve el token endpoint y el JWKS con el host de
la petición. MCP Auth valida contra el `issuer` y el `jwks_uri` del discovery, no contra la URL desde la que lo
descargó. Por eso el servidor del contenedor acepta los tokens pedidos desde el host (Playground, `curl`) y los del
agente del contenedor `api`, que los pide a `keycloak:8080`.

| Variable | Uso |
| --- | --- |
| `MCP_OAUTH_ISSUER` | Issuer OIDC (realm `trackflow` de Keycloak). Al arrancar se descarga su configuración y JWKS |
| `MCP_RESOURCE_URL` | URL pública del endpoint MCP; es el `resource` de la metadata (en Codespaces, la URL reenviada del 8001 + `/mcp`) |
| `MCP_SERVICE_USER_ID` | Cuenta activa de `auth.json` con la que el servidor llama a la API (JWT HS256 de 5 minutos firmado con `JWT_SECRET_KEY`) |
| `TRACKFLOW_API_URL` | API de TrackFlow (por defecto `http://127.0.0.1:8000`) |
| `MCP_HOST`, `MCP_PORT` | Interfaz y puerto (por defecto `0.0.0.0:8001`) |

**Códigos de salida del proceso:** `0` parada normal · `2` falta una variable obligatoria (el log dice cuál) ·
`3` el issuer OAuth no responde o su configuración OIDC no es válida.

## OAuth con MCP Auth

- **Proveedor:** Keycloak 26 (`docker compose up -d keycloak`, realm importado de `infra/keycloak/trackflow-realm.json`).
- **Resource server:** `mcpauth` (0.2.0b1, la primera versión con Protected Resource Metadata). No se usa la auth de
  FastMCP.
- `GET /.well-known/oauth-protected-resource/mcp` (pública) devuelve `resource`, `authorization_servers` y
  `scopes_supported`.
- Toda petición a `/mcp` (incluido `tools/list`) pasa por el middleware bearer de MCP Auth: firma contra el JWKS del
  issuer, issuer exacto, audiencia `trackflow-mcp` y expiración. Si algo falla responde 401 con `WWW-Authenticate` y
  la URL de la metadata, y la petición no llega a FastMCP.

### Scopes (mínimo privilegio)

| Scope | Permite |
| --- | --- |
| `incidents:read` | `get_ticket_status` |
| `incidents:write` | `create_ticket`, `update_ticket_status` |
| `inventory:read` | `query_inventory` |

No existe ningún scope de escritura de inventario. Cada tool comprueba su scope en `middleware.py`. El middleware de
MCP Auth no usa `required_scopes` global porque cada tool exige un scope distinto y un único requisito común daría
más permisos de los necesarios.

| Cliente de Keycloak | Scopes | Uso |
| --- | --- | --- |
| `support-agent` | `incidents:read` | El agente LangGraph (`services/support_agent`) |
| `trackflow-operator` | los tres | Pruebas manuales (MCP Playground) |

Los dos clientes usan `client_credentials`; sus secretos salen del `.env` (`KEYCLOAK_AGENT_CLIENT_SECRET`,
`KEYCLOAK_OPERATOR_CLIENT_SECRET`).

## Tools (discovery)

`tools/list` devuelve para cada tool su nombre, título, descripción (con el scope que exige), el JSON Schema de
entrada y de salida, y las anotaciones `readOnlyHint` / `destructiveHint` / `idempotentHint`. Las `instructions` del
servidor resumen el dominio y los códigos de error. Los valores de dominio son los de la API: `category`, `origin`,
`branch` y `status` del gestor de incidencias, y `warehouse` `LA`/`ZGZ` del inventario.

| Tool | Entrada | Salida | Llamada a la API |
| --- | --- | --- | --- |
| `create_ticket` | `title`, `description`, `category`, `origin`, `branch` | Ticket | `POST /api/incidents` (nace `open`) |
| `update_ticket_status` | `ticket_id`, `status` | Ticket | `PATCH /api/incidents/{id}/status` (endpoint de ciclo de vida) |
| `get_ticket_status` | `ticket_id` | Ticket | `GET /api/incidents/{id}` |
| `query_inventory` | `operation` (`list_products`, `get_product`, `list_movements`), `sku_id?`, `warehouse?` | `{operation, products \| product \| movements}` | Solo `GET /inventory/products`, `/inventory/products/{id}`, `/inventory/orders` |

El Ticket tiene `id`, `title`, `description`, `status`, `category`, `origin`, `branch`, `created_at` y `updated_at`.
Omite `reported_by`, que es el email interno de quien lo registró.

### Inventario de solo lectura por diseño

1. No existe ningún scope que permita escribir en el inventario.
2. El único acceso del servidor al inventario es `backend.InventoryReader`, que solo sabe hacer `GET` bajo
   `/inventory`.
3. `query_inventory` reconoce las escrituras de la API de inventario (`create_product`, `update_product`,
   `delete_product`, `update_stock`, `create_inbound_order`, `create_outbound_order`, `create_inventory_count`) y las
   rechaza con `INVENTORY_READ_ONLY` antes de hacer ninguna petición. Un cliente que lo intente recibe un motivo claro,
   no una tool desconocida ni un error genérico.

## Errores

**Autenticación (HTTP, MCP Auth).** El cuerpo es `{error, error_description}` y la cabecera `WWW-Authenticate` incluye
`resource_metadata`.

| HTTP | `error` | Causa |
| --- | --- | --- |
| 401 | `missing_auth_header` | Sin cabecera `Authorization` |
| 401 | `invalid_auth_header_format` / `missing_bearer_token` | Cabecera que no es `Bearer <token>` |
| 401 | `invalid_token` | JWT mal formado, firma no válida o expirado |
| 401 | `invalid_issuer` | Token de otro issuer |
| 401 | `invalid_audience` | Token para otra API (audiencia distinta de `trackflow-mcp`) |

**Autorización y validación (tool, `isError: true`).** El contenido es un JSON `{code, message, errors?}`.

| `code` | Tipo | Causa |
| --- | --- | --- |
| `INSUFFICIENT_SCOPE` | Autorización | El token no tiene el scope de la tool; el mensaje dice cuál falta |
| `INVENTORY_READ_ONLY` | Autorización | Se pidió una operación de escritura sobre el inventario |
| `VALIDATION_ERROR` | Validación | Argumentos fuera del esquema, o regla de negocio de la API (p. ej. transición de estado no permitida); `errors[{field, message}]` |
| `NOT_FOUND` | Validación | El ticket o el SKU no existen |
| `UPSTREAM_UNAVAILABLE` | Disponibilidad | La API de TrackFlow no respondió, tardó más de 5 s o falló |

## Logs

El logger `trackflow.mcp` escribe una línea por invocación de tool:

```
tool_call tool=update_ticket_status client=trackflow-operator subject=<sub> result=ok duration_ms=40
tool_call tool=create_ticket client=support-agent subject=<sub> result=INSUFFICIENT_SCOPE duration_ms=0
```

`client` es el `azp`/`client_id` del token, `subject` es su `sub` y `result` es `ok` o el código de error. Los fallos
de la API se registran aparte con el método, la ruta y el estado HTTP.

## Validación con MCP Playground (GitHub Codespaces)

MCP Playground autentica con cabeceras HTTP, así que no hace falta exponer Keycloak: el token se pide dentro del
Codespace y se pega como cabecera.

1. En el `.env` del Codespace, pon en `MCP_RESOURCE_URL` la URL reenviada del puerto 8001 más `/mcp`
   (`https://<codespace>-8001.app.github.dev/mcp`).
2. Levanta `docker compose up -d keycloak api mcp` (o el servidor en el host, ver "Arranque").
3. En la pestaña **Ports**, cambia la visibilidad del 8001 a **Public**.
4. Pide un token del operador (válido 5 minutos):

   ```bash
   set -a; . ./.env; set +a
   curl -s -X POST "$MCP_OAUTH_ISSUER/protocol/openid-connect/token" \
     -d grant_type=client_credentials -d client_id=trackflow-operator \
     -d client_secret="$KEYCLOAK_OPERATOR_CLIENT_SECRET" | jq -r .access_token
   ```

5. En <https://www.mcpplayground.tech/playground>, conecta a la URL reenviada (`…-8001.app.github.dev/mcp`) con la
   cabecera `Authorization: Bearer <token>`.
6. Ejecuta un flujo por tool:
   - `create_ticket` → `update_ticket_status` (`in_progress`) → `get_ticket_status`.
   - `query_inventory` con `list_products`, `get_product` y `list_movements`.
7. Intento de escritura: `query_inventory` con `{"operation": "create_inbound_order", "sku_id": 1}`. Debe devolver
   `isError: true` con `{"code": "INVENTORY_READ_ONLY", "message": "El inventario es de solo lectura en este servidor:
   la operación 'create_inbound_order' no está permitida para ningún cliente. …"}`. El log muestra
   `result=INVENTORY_READ_ONLY` y la API no recibe ninguna petición.

Sin la cabecera, la conexión falla con 401 `missing_auth_header` y Playground no puede listar las tools.

## Tests

```bash
uv run pytest tests/mcp -v                                # servidor: OAuth, discovery, tools, scopes, errores, logs, salida
uv run pytest tests/pipelines/test_incidents_tool.py -v   # el agente como cliente MCP
```

Los tests arrancan el servidor real en un hilo (`tests/mcp_harness.py`). Los tokens se firman con una clave RSA de
prueba cuyo JWKS sustituye al de Keycloak; los tickets van contra la API FastAPI real con TinyDB temporal.
