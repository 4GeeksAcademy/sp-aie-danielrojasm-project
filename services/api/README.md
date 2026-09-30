# TrackFlow API

API de autenticación, proveedores, incidencias e inventario. Usa dos bases de
datos a la vez:

- **TinyDB** (JSON local): usuarios y perfiles, proveedores e incidencias. Las
  contraseñas se almacenan con bcrypt y la autenticación usa JWT stateless.
- **Supabase (PostgreSQL) con SQLModel**: inventario — SKUs, recepciones
  (`StockEntry`) y salidas (`StockExit`). Los movimientos guardan el UUID del
  usuario de TinyDB en `user_uuid`; no hay tabla de usuarios en PostgreSQL.

## Ejecutar

```bash
uv sync
uv run uvicorn services.api.main:app --reload --port 8000 --env-file .env
```

La configuración local vive en `.env` y no se versiona:

```dotenv
JWT_SECRET_KEY=una-clave-aleatoria-larga
ACCESS_TOKEN_EXPIRE_MINUTES=30
RESEND_API_KEY=tu-clave-de-resend
RESEND_FROM_EMAIL=onboarding@resend.dev
PASSWORD_RESET_URL=http://localhost:3002/reset-password
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
TELEMETRY_ENDPOINT=http://localhost:8000/telemetry/events
TELEMETRY_ENVIRONMENT=development
TELEMETRY_HASH_KEY=otra-clave-aleatoria-larga
STOCK_MIN_THRESHOLDS={"purestep-footwear": 80}
```

`DATABASE_URL` es la URI del **Transaction pooler** de Supabase (Connect →
Direct). Al arrancar, la API crea las tablas que falten
(`SQLModel.metadata.create_all`). Sin `DATABASE_URL`, o si PostgreSQL no
responde, la API arranca igual y las rutas de `/inventory` responden `503`.

`RESEND_API_KEY` es obligatoria para enviar correos reales. Con el remitente de
onboarding de Resend solo se puede enviar al email de la cuenta Resend; para
otros destinatarios configura `RESEND_FROM_EMAIL` con un dominio verificado.
El envío usa el SDK oficial de Resend, sin claves incrustadas en el código.
`PASSWORD_RESET_URL` debe apuntar a la ruta pública del backoffice (incluido
el origen correcto en despliegue). En Codespaces, si apunta a `localhost`,
se sustituye automáticamente por la URL HTTPS del puerto reenviado. El puerto
3002 puede requerir iniciar sesión en GitHub antes de mostrar la página.
Nunca publiques la clave en el repositorio.
Si el proveedor falla, la respuesta de recuperación sigue siendo genérica y
el fallo se registra en el servidor sin incluir el enlace ni el token.

`AUTH_DB_PATH` permite cambiar la ubicación de `services/api/auth.json`, por
ejemplo para aislar pruebas. La API no arranca sesiones ni usa cookies.

El backoffice se sirve en `http://localhost:3002` y reenvía `/api/incidents/*`
al servicio desde Next, en el mismo origen que la página. En Codespaces, no hace
falta exponer el puerto 8000 al navegador. Si la API se ejecuta en otro host,
configura `INCIDENTS_API_INTERNAL_URL` en el proceso del backoffice.
`BACKOFFICE_ORIGIN` permite autorizar otro origen si se consume la API
directamente.

## Endpoints

- `POST /users`: registra credenciales y crea su perfil uno a uno. Es público.
- `GET/PUT/DELETE /users`: CRUD protegido; el listado global y el acceso o la
  modificación de otro usuario requieren rol `admin`.
- `POST /auth/login`: acepta JSON (`email`, `password`) y el formulario OAuth2
  (`username` contiene el email). Devuelve un bearer token.
- `POST /auth/forgot-password`: acepta `email`; responde siempre 200 y envía
  por Resend un enlace si la cuenta existe. El token dura 30 minutos.
- `POST /auth/reset-password`: acepta `token` y `new_password`; el token firmado
  solo puede usarse una vez. Responde 400 para enlaces inválidos o caducados.
- `POST /auth/change-password`: requiere bearer; acepta `current_password` y
  `new_password`, y responde 400 si la contraseña actual es incorrecta.
- `GET /auth/me` y `GET/PUT /profiles/me`: devuelven o actualizan los datos del
  usuario autenticado.
- Todas las rutas de `/suppliers` requieren un bearer token.
- `POST /api/incidents/analyze`: requiere token, recibe el campo multipart `file` y devuelve el
  resumen JSON. CSV vacío, cabecera incompatible o contenido inválido responde
  `400` con un mensaje que no incluye valores del fichero.
- `GET /api/incidents/results/export`: descarga las métricas agregadas del
  último análisis correcto como CSV y requiere token. Antes de un análisis
  responde `404`.
- `GET /`: informa que el servicio está activo.

### Gestor de incidencias (`/api/incidents`)

Persistencia en TinyDB (`services/api/incidents.json`, configurable con
`INCIDENTS_DB_PATH`, no versionado). Todas las rutas requieren bearer token.
Los valores permitidos y el ciclo de vida vienen de
`packages/shared/incidents/domain.py`.

- `POST /api/incidents`: crea una incidencia (`title` ≤ 120, `description`,
  `category`, `origin`, `branch`). El estado inicial es siempre `open`;
  `reported_by` se toma del usuario autenticado. Responde `201`.
- `GET /api/incidents`: listado (más recientes primero) con filtros opcionales
  `status`, `origin`, `branch` y `category`.
- `GET /api/incidents/{id}`: detalle; `404` si no existe.
- `PATCH /api/incidents/{id}/status`: `open → in_progress | discarded`,
  `in_progress → resolved | discarded`; `resolved` y `discarded` son finales.
- `GET /api/incidents/summary`: `total`, `by_status`, `by_category`,
  `by_origin` y `by_branch`, con todas las claves a cero si no hay datos.

Los errores de validación de estas rutas responden `400` con
`{"detail": "...", "errors": [{"field": "title", "message": "..."}]}`. El resto
de la API mantiene el `422` estándar de FastAPI. Cualquier excepción no
controlada responde `500` con un mensaje genérico y se registra en el log
`trackflow.api`, sin exponer la traza.

Carga del histórico CSV (idempotente, desde la raíz):

```bash
uv run python scripts/seed_incidents.py [ruta.csv]
```

### Inventario (`/inventory`)

Modelos ORM en `models.py`, schemas de request/response en `schemas.py` y
router en `routes/inventory.py`. La sesión de SQLModel se inyecta por petición
con `Depends(get_db)` (`database.py`). Todas las rutas requieren bearer token:
el inventario es información contractual de las marcas cliente.

- `GET /inventory/products`: SKUs con su stock; filtro opcional `warehouse`
  (`LA` o `ZGZ`).
- `POST /inventory/products`: registra un SKU (`name`, `sku`, `client_name`,
  `category` = `fashion | electronics | cosmetics`, `warehouse`). Empieza con
  stock 0; un código repetido responde `409`.
- `GET /inventory/products/{id}`: un SKU con su stock; `404` si no existe.
- `POST /inventory/orders/inbound`: recepción (`sku_id`, `quantity` > 0,
  `reference`, `warehouse`).
- `POST /inventory/orders/outbound`: salida (`sku_id`, `quantity` > 0,
  `exit_type` = `dispatch | loss`, `tracking_number`, `warehouse`).
  `tracking_number` es obligatorio en `dispatch` y debe omitirse en `loss`
  (`422`). Si la salida supera el stock del almacén responde `400` con
  `Insufficient stock for SKU '<sku>'. Available: <n>, requested: <m>.` sin
  escribir nada.
- `GET /inventory/orders`: recepciones y salidas (más recientes primero) con
  los datos del SKU, `user_uuid` y filtro opcional `warehouse`.
- `POST /inventory/counts`: conteo físico (`sku_id`, `warehouse`,
  `counted_quantity` ≥ 0, `detection_method` = `cycle_count | audit`). Compara
  lo contado con el stock calculado (con la fila del SKU bloqueada) y devuelve
  `system_quantity` y `difference`. **No cambia el stock**: un descuadre se
  corrige con una recepción o una salida `loss`.
- `PUT`/`PATCH`/`DELETE` sobre `/inventory/products/{id}`,
  `/inventory/products/{id}/stock` y `/inventory/orders/**`: siempre `405` con
  «El stock solo cambia con órdenes de entrada o salida.».

**Stock.** No existe ninguna columna de stock ni ruta que lo modifique: se
calcula como `SUMA(recepciones) − SUMA(salidas)` por SKU **y por almacén**, con
dos consultas agregadas. `current_stock` es el stock del SKU en el almacén donde
está dado de alta, y `stock_by_warehouse` muestra la cifra de cada almacén por
separado (nunca se suman). Una salida se valida contra el stock de su propio
almacén, con la fila del SKU bloqueada (`SELECT … FOR UPDATE`) para que dos
salidas simultáneas no lo dejen en negativo. La base de datos refuerza las
reglas con restricciones `CHECK` (cantidades > 0, valores permitidos y
`tracking_number` coherente con `exit_type`) y claves foráneas a `skus`.

Datos iniciales (6 SKUs, 7 recepciones y 4 salidas; idempotente, desde la
raíz). `--user-email` es el usuario de TinyDB que firma los movimientos:

```bash
uv run --env-file .env python scripts/seed_inventory.py --user-email tu@email.com
```

En `/docs`, registra un usuario, abre **Authorize** y usa su email como
`username` y su contraseña. Swagger obtiene el token desde `/auth/login` y lo
envía en las rutas protegidas.

### Telemetría (`/telemetry`)

- `POST /telemetry/events`: **receptor provisional** de los lotes del
  backoffice (`{"events": [...]}`, máximo 100). Valida el Event Envelope de
  cada evento (`TelemetryEvent` en `telemetry_models.py`), registra en
  `trackflow.telemetry` cuántos eventos llegan y su `event_type`, y responde
  `{"received": N}`. Acepta el cuerpo como `application/json` o `text/plain`
  (`sendBeacon`). No persiste nada ni exige token todavía.

La API emite sus propios eventos con `telemetry.emit()` (`telemetry.py`): los
cinco obligatorios de inventario tras el `commit`, rechazos de salidas y altas,
validación del servidor, login y errores `500`. Salen como una línea JSON por
evento en el log `trackflow.telemetry`, solo con las claves del allowlist de
`docs/telemetry/event-schemas.json` (en Docker se monta en
`/app/docs/telemetry`; otra ruta con `TELEMETRY_SCHEMA_PATH`).

- `TELEMETRY_ENDPOINT`: URL de la ingesta; hoy el receptor de arriba.
- `TELEMETRY_ENVIRONMENT`: `development`, `staging` o `production`.
- `TELEMETRY_HASH_KEY`: clave del HMAC del email en `user_login_failed`. Sin
  ella, `email_hash` sale nulo.
- `STOCK_MIN_THRESHOLDS`: mínimo de stock por `client_id` (JSON); por defecto,
  50 unidades. Una salida que lo cruza emite `stock_threshold_triggered`.

Cada respuesta lleva `X-Request-Id` (el que envía el backoffice o uno nuevo);
el mismo id aparece en la línea de `trackflow.timing` y en los eventos de la
petición.

## Pruebas

```bash
uv run pytest          # toda la batería (ver TESTING.md en la raíz)
uv run pytest tests/inventory
```

El resumen más reciente vive en memoria del proceso y se reemplaza tras cada
carga correcta; no se persiste el fichero ni sus registros.