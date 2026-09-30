# Tech context del monorepo TrackFlow

## AI Engineering · 4Geeks Academy — Banco de memoria: contexto técnico

---

Este archivo describe cómo está construido el monorepo: qué hay en cada carpeta, con qué stack, qué decisiones de arquitectura se han
tomado y qué restricciones técnicas están en vigor. Hay que actualizarlo cada vez que cambie cualquiera de ellas.

El monorepo parte de la plantilla del programa de 4Geeks Academy. Contiene la lógica de negocio del Hito 2 en `src/`, tres interfaces
en `uis/`, la configuración de agentes de código del Hito 4 y `services/api`, una API interna para analizar incidencias.

## Mapa del monorepo

- **`src/`** — lógica de negocio del Hito 2 en TypeScript puro y sin dependencias (`types/models.ts` y
  `utils/{collections,search,transformations,validations}.ts`). Es la fuente única: se importa, no se copia.
- **`uis/website/`** — web pública (Hito 1 migrado a Next.js), con las rutas `/` y `/aplicar`.
- **`uis/backoffice/`** — app interna de la empresa. Su ruta `/` es el panel de operaciones que consume `src/`.
- **`uis/talent-pipeline-tracker/`** — gestor de candidaturas contra una API REST externa.
- **`services/`** — APIs y workers. `services/api/` contiene la API FastAPI de análisis de incidencias; el servicio principal de operaciones sigue pendiente.
- **`packages/shared/`** — paquete `@repo/shared-types` de la plantilla (sin uso) y `incidents/`, lógica Python de incidencias
  compartida por `services/api` y `scripts/` (se importa como `packages.shared.incidents.*` desde la raíz).
- **`memory-bank/`, `AGENTS.md`, `.agents/`** — configuración de los agentes de código (Hito 4).
- **`agents/`, `skills/`, `mcps/`, `workflows/`, `data/`, `infra/`** — espacio para el producto de hitos futuros (agentes de la empresa,
  no del IDE). Solo contienen la plantilla.

---

## Stack

### ⚙️ Runtime y lógica de negocio

**Node.js:** 24.x LTS (instalado con winget en la máquina de desarrollo)

**TypeScript en la raíz:** `typescript ^6.0.3`. El `tsconfig.json` raíz es `strict`, usa `moduleResolution: Bundler` y solo incluye
`src/**/*.ts`.

**Python:** el CLI y `services/api/incidents_analyzer.py` usan la biblioteca estándar para validar y agregar el CSV en streaming. El analizador y el seed validan con `packages/shared/incidents/csv_validation.py`. La API usa
FastAPI, `python-multipart` y Uvicorn, declarados en `services/api/requirements.txt`.

---

### 🖥️ Frontends

**Framework:** Next.js 16.2.10 (App Router, Turbopack) con React 19.2.4, las mismas versiones en las tres apps.

**Estilos:** Tailwind CSS v4 mediante `@tailwindcss/postcss`, sin `tailwind.config.js`. Los tokens están en `app/globals.css` con `@theme`.

**Calidad:** ESLint 9 (flat config) con `eslint-config-next` 16.2.10 y TypeScript 5 en cada app.

Next 16 trae cambios incompatibles con versiones anteriores. Antes de usar una API de Next hay que leer su guía en
`uis/<app>/node_modules/next/dist/docs/`, como exige el `AGENTS.md` de cada app.

---

## Decisiones de arquitectura

### 📦 Apps independientes, sin npm workspaces

Cada app de `uis/` tiene su propio `package.json` y `package-lock.json`. El Hito 3 ya funcionaba así y la plantilla no define un runner de
workspaces. Por eso `npm install` se ejecuta dentro de cada app, o con `npm run install:uis` desde la raíz.

---

### 🔗 La lógica del Hito 2 se importa, nunca se copia

El backoffice resuelve `src/` con el alias `@trackflow/logic/*` → `../../src/*` (en `uis/backoffice/tsconfig.json`) y amplía
`turbopack.root` y `outputFileTracingRoot` a la raíz del monorepo (en `uis/backoffice/next.config.ts`), porque Turbopack no resuelve
archivos fuera de su raíz. La web, en cambio, fija `turbopack.root` a su propia carpeta para que Next no tome el `package-lock.json` de la
raíz como raíz del proyecto.

---

### 🧩 Contenido, validación y etiquetas separados de la presentación

Los textos, enlaces y datos de empresa de la web están en `uis/website/content/site.ts`, tipados en `uis/website/types/site.ts`. Las
validaciones del formulario son funciones puras en `uis/website/lib/application-form.ts`, portadas del antiguo `uis/website/validation.js` del Hito 1 (eliminado en el Hito 4). Las
etiquetas en español de los valores de dominio están centralizadas en `uis/backoffice/lib/labels.ts` como `Record<Tipo, string>`, de modo
que un valor nuevo del modelo rompe el tipado en lugar de mostrarse crudo.

---

### 🎨 Layouts separados

La web pública tiene cabecera y footer oscuros con la marca (`slate-950` y `cyan-300`). El backoffice tiene sidebar y barra superior, fondo
claro y `robots: noindex`. No comparten layout ni componentes.

---

### Directorio de proveedores — Milestone 09

`services/api/` también expone el directorio persistente `/suppliers`, implementado con FastAPI, Pydantic y TinyDB. El seeder se ejecuta
con `uv run seed`, es idempotente y carga los 15 proveedores de referencia de TrackFlow. `uis/backoffice` consume estas rutas mediante
el rewrite `/api/suppliers/*` y muestra el directorio en `/suppliers`.

### Autenticación JWT — Milestone 09

AUTH-03 guarda el hash SHA-256 del JWT de recuperación en la tabla TinyDB
`password_resets`; el token lleva propósito exclusivo y expira en 30 minutos.
El reset o cualquier cambio de contraseña borra los tokens pendientes. Resend
recibe el enlace mediante `RESEND_API_KEY` (remitente `RESEND_FROM_EMAIL`, URL
`PASSWORD_RESET_URL`) a través del SDK oficial `resend`. El backoffice ofrece rutas públicas `/forgot-password` y
`/reset-password`, y ruta protegida `/account/change-password`.
En Codespaces, la API transforma la URL de reset local en el origen HTTPS del
puerto reenviado; las URL externas explícitas se mantienen. Las rutas de
recuperación siguen accesibles incluso con una sesión iniciada.

`services/api/` mantiene usuarios y perfiles exclusivamente en TinyDB
(`auth.json`, tablas `users` y `profiles`) con UUID propios. Las contraseñas se
hashean con `libpass[bcrypt]`; `python-jose` firma JWT HS256 cuyo `sub` es el ID
TinyDB del usuario. `JWT_SECRET_KEY` y `ACCESS_TOKEN_EXPIRE_MINUTES` se leen del
entorno. `OAuth2PasswordBearer` protege el CRUD de usuarios, los perfiles, todas
las rutas de proveedores y las dos rutas de incidencias; el health check y el
registro permanecen públicos.

El backoffice completa el flujo con autenticación exclusivamente cliente:
`AuthProvider` restaura el usuario mediante `/auth/me`, `ProtectedShell` protege
las vistas internas sin `middleware.ts` y `apiFetch` conserva el JWT en
`localStorage`, añade el header `Authorization` y redirige a `/login` ante
`401`. Los rewrites de Next mantienen las peticiones en el origen del
backoffice. `uis/website` no participa en este flujo y sigue siendo público.

### Gestor de incidencias — Milestone 09

`services/api/routes/incidents.py` persiste incidencias en TinyDB (`incidents.json`, `INCIDENTS_DB_PATH`, ignorado por git) con
id entero de TinyDB. Enums, transiciones y el mapeo CSV → modelo están en `packages/shared/incidents/domain.py`; la validación de
filas del CSV, en `csv_validation.py`, compartida con el analizador. Solo las rutas `/api/incidents*` convierten los errores de
validación en `400` con `errors[{field, message}]`; el resto de la API mantiene `422`. Un handler global devuelve `500` genérico
y registra la traza en el log `trackflow.api`. Toda incidencia nueva nace `open` y guarda `reported_by` (email del JWT).
El seed (`scripts/seed_incidents.py`) no guarda `incident_id` en la incidencia: lo registra en la tabla de control
`seed_imports` para ser idempotente. El backoffice muestra solo mensajes propios (`uis/backoffice/lib/incidents.ts`), nunca el
texto de la API.

### Inventario con doble base de datos — Hito 5

`services/api` usa dos bases a la vez: TinyDB para auth, proveedores e incidencias, y Supabase (PostgreSQL, `DATABASE_URL`,
Transaction pooler) con SQLModel para el inventario. `database.py` tiene el motor único (`get_engine`, `pool_pre_ping`) y la
dependencia `get_db`, que abre una sesión por petición; no hay sesiones globales. Tablas `skus`, `stock_entries` y `stock_exits`
(`models.py`); schemas separados en `schemas.py`; router `routes/inventory.py` con prefijo `/inventory` y bearer en todas las rutas.
El stock no se almacena: `SUMA(entradas) − SUMA(salidas)` por SKU y almacén con dos `GROUP BY`; `current_stock` es el del almacén
del SKU y `stock_by_warehouse` desglosa LA/ZGZ. Las salidas bloquean la fila del SKU (`FOR UPDATE`) antes de comprobar el stock.
`user_uuid` es el id de TinyDB, sin FK. Integridad reforzada con `CHECK` en PostgreSQL. Sin `DATABASE_URL` o con PostgreSQL caído,
la API arranca y `/inventory` responde 503. Para liberar los nombres, el antiguo `models.py` de proveedores pasó a
`supplier_models.py` y el `get_db` de TinyDB a `get_suppliers_db`. No hay migraciones: `create_all` solo crea tablas que falten, así
que cambiar una columna existente exigirá introducir Alembic.

El backoffice consume el inventario desde `uis/backoffice/lib/inventory.ts`, único módulo que llama a `/inventory` (vía
`requestJson`, con Bearer y 401 → `/login`). El rewrite `/api/inventory/*` apunta a `NEXT_PUBLIC_INVENTORY_API_URL` (en `.env.local`,
ignorado por git) o, si falta, al origen general de la API. Las vistas cuelgan de `/inventory/*` dentro de `ProtectedShell`. El
umbral de stock bajo (`LOW_STOCK_THRESHOLD = 50`) vive en ese módulo; el aviso de cantidad superior al stock es solo UX y la regla
real la aplica la API con su 400.

### Serialización de la API — Milestone 09

Todo endpoint JSON declara un `response_model` Pydantic con nombre y el handler construye ese esquema explícitamente
(nunca devuelve `User`, `Profile` ni filas del ORM). Convención: `*Create`/`*Update`/`*Request` con `extra="forbid"`
para la entrada; `*Read` (o el modelo de detalle) para el detalle y las escrituras; `*ListItem` con solo las columnas
de la tabla para los listados; `MessageResponse` y `HealthResponse` en `services/api/common_models.py`. Las
relaciones se aplanan si la UI solo lee unos campos (historial de inventario). Excepciones declaradas con
`response_model=None`: `DELETE /users/{id}` (204) y la exportación CSV. `tests/http/test_serialization.py` recorre
`app.openapi()` y falla si una ruta nueva no cumple (en FastAPI 0.141 los routers incluidos no aparecen como
`APIRoute` en `app.routes`). Detalle por endpoint en `docs/serialization-audit.md`.

### Caché de la API y timing — Milestone 09

`services/api/cache.py` define `TTLCache`, una caché en memoria **por proceso** con TTL obligatorio,
`invalidate()` y un número de generación que impide guardar un valor leído antes de un commit. Solo se usa
para respuestas iguales para cualquier usuario autenticado: `products_cache` (`GET /inventory/products`,
TTL 30 s, clave = filtro de almacén) y `summary_cache` (`GET /api/incidents/summary`, TTL 60 s). Toda
escritura que cambia esos datos invalida después del commit; la regla de stock de las salidas nunca lee
de la caché. Con varios workers o réplicas, cada proceso tiene su copia y el TTL es el máximo de
desactualización (Redis sería el siguiente paso). `tests/conftest.py` vacía las cachés entre tests.
El middleware `timing_middleware` registra cada petición en `trackflow.timing` y añade `Server-Timing`;
`_configure_logging()` da handler al logger `trackflow`, porque uvicorn solo configura los suyos.
Decisiones y mediciones en `audit/caching/CACHING_REPORT.md`.

### Telemetría: captura implementada, almacenamiento pendiente — Milestone 09

El contrato está en `docs/telemetry/telemetry-plan.md`; `docs/telemetry/event-schemas.json` es la fuente validable (draft-07,
allowlist con `additionalProperties: false`). Los eventos obligatorios de inventario los emite solo la API; el navegador aporta
contexto de UX. Correlación por `X-Request-Id` (una por llamada de `apiFetch`) y `X-Session-Id` (una por pestaña). En eventos:
`LA`/`ZGZ` → `los_angeles`/`zaragoza`, `client_id` = slug de `client_name` (misma función en Python y TS, con los mismos casos de
prueba), `product_id` = código SKU.

- **Backoffice:** `lib/telemetry.ts` es el único módulo que llama a la ingesta (`fetch` con `keepalive` y `sendBeacon` como
  `text/plain`, sin preflight). `track()` está tipado con `lib/telemetry-events.ts`; `lib/telemetry-reporters.ts` aplica los throttles
  del plan. `TelemetryListener` (layout raíz) captura vistas, errores globales y Web Vitals. `NEXT_PUBLIC_TELEMETRY_ENDPOINT` y
  `NEXT_PUBLIC_TELEMETRY_ENVIRONMENT` viven en el `.env` raíz: `next.config.ts` copia solo las `NEXT_PUBLIC_TELEMETRY_*` (el resto del
  archivo trae URLs de Docker) y respeta las que ya estén en el entorno. Sin endpoint, la telemetría queda desactivada. Rewrite
  `/api/telemetry/*` para Codespaces.
- **API:** `telemetry.py` lee el allowlist, la versión y el emisor de cada evento de `event-schemas.json` (montado en Docker en
  `/app/docs/telemetry`) y solo emite eventos cuyo emisor incluye `api`. Sumideros en `SINKS`: hoy, el log `trackflow.telemetry`.
  `routes/telemetry.py` es un stub que solo valida el envelope (`telemetry_models.TelemetryEvent`). `TELEMETRY_ENDPOINT`,
  `TELEMETRY_ENVIRONMENT`, `TELEMETRY_HASH_KEY` (HMAC del email) y `STOCK_MIN_THRESHOLDS`.
- **Inventario:** nueva tabla `inventory_counts` (la crea `create_all`, no modifica tablas existentes) y rutas 405 explícitas contra
  la edición directa del stock. Las 12 rutas 405 declaran su esquema de error; `tests/http/test_serialization.py` las cuenta aparte.
- **Restricciones abiertas:** sin outbox, un evento obligatorio se pierde si el proceso cae entre el `commit` y el log. El umbral se
  dispara comparando stock anterior y resultante en la salida; una recepción concurrente no bloquea la fila del SKU, así que en una
  carrera `stock_after` puede quedar desfasado hasta que exista `stock_threshold_alerts`. El stub no exige token: cualquiera que
  alcance la API puede enviar eventos hasta que llegue la ingesta real.

### 🚫 Sin APIs dentro de `uis/`

Nada de `app/api/*` ni route handlers en las interfaces. Cuando haga falta backend, se crea en `services/<nombre>`. Mientras tanto, el
backoffice usa datos de ejemplo en `uis/backoffice/lib/sample-data.ts` (el dataset de referencia del Hito 2 más FedEx y envíos extra), que se
sustituirán por la API de `services/` en el Hito 5.

### 📊 Análisis interno de incidencias

El módulo `services/api/incidents_analyzer.py` es compartido por el CLI `scripts/incidents-analyzer/analyze.py` y los endpoints de
`services/api/main.py`. Procesa filas en streaming, no persiste registros ni exporta datos personales; FastAPI conserva en memoria solo el
último resumen correcto. El backoffice consume la API desde `/incidents/analyzer` y llama a `/api/incidents/*` en el mismo origen; un rewrite de Next
reenvía la petición desde el servidor a `INCIDENTS_API_INTERNAL_URL` (predeterminado `http://127.0.0.1:8000`). El navegador no requiere acceso
directo al puerto privado de la API.

---

### 🐳 Entorno de desarrollo en Docker Compose — Ticket #infra-40

`docker compose up` desde la raíz levanta dos servicios en la red `trackflow-dev`:

- **`api`** (`services/Dockerfile`, `python:3.12-slim` + `uv pip install --system -r api/requirements.txt`): Uvicorn con
  `--reload` sobre `services/` y `packages/`, montados por bind mount desde `/app`, porque la API se importa como
  `services.api.main` y usa `packages.shared`. Recibe `.env` entero (`env_file`). `BACKOFFICE_ORIGIN` y `PASSWORD_RESET_URL`
  se sobrescriben con `DOCKER_BACKOFFICE_ORIGIN` y `DOCKER_PASSWORD_RESET_URL`, porque en el contenedor el backoffice va en el
  3001 y en local sigue en el 3002. Healthcheck contra `GET /`.
- **`uis`** (`uis/Dockerfile`, `node:24-alpine`): `npm ci` por separado en website y backoffice; `uis/start.sh` arranca
  `next dev` de la web en el 3000 y del backoffice en el 3001, y sale si una de las dos cae. Monta `uis/`, más `src/` y el
  `tsconfig.json` raíz (solo lectura) para que `turbopack.root` (= `/app`) resuelva `@trackflow/logic`. `node_modules` y `.next`
  de cada app van en volúmenes anónimos: los binarios son de Alpine, no del host. Solo recibe `TRACKFLOW_API_INTERNAL_URL` y
  `NEXT_PUBLIC_INVENTORY_API_URL` (`http://api:8000`, por nombre de servicio), nunca los secretos de la API. Estas variables del
  proceso tienen prioridad sobre `uis/backoffice/.env.local`, que también llega por el bind mount.
- Todas las variables salen de `.env` (plantilla en `.env.example`); el YAML falla con mensaje (`${VAR:?}`) si falta alguna.
- Tras cambiar un `package.json` o `requirements.txt`: `docker compose up --build -V` (renueva los volúmenes anónimos).
- `talent-pipeline-tracker` no está en el contenedor de interfaces.
- **Codespaces:** el Docker-in-Docker del Codespace arrastra una tabla `iptables-legacy` con `FORWARD DROP` que solo acepta
  `docker0`; en una red con nombre (`br-*`) los contenedores no se ven entre sí ni salen a internet (el DNS interno sí resuelve).
  No ocurre en Docker Desktop ni en un Docker Engine estándar.

---

## Puertos de desarrollo

- **`uis/website`** — puerto **3000**, con `npm run dev` o `npm run dev:website` desde la raíz.
- **`uis/backoffice`** — puerto **3002**, con `npm run dev` o `npm run dev:backoffice` desde la raíz.
- **`services/api`** — puerto **8000**, con `uvicorn services.api.main:app --reload --port 8000` desde la raíz.
- **`uis/talent-pipeline-tracker`** — puerto 3000 por defecto, que choca con la web. Se arranca con `npm run dev -- --port 3003`.

El backoffice **no** usa el 3001 porque el tracker del Hito 3 usa `http://localhost:3001` como API por defecto cuando no existe
`NEXT_PUBLIC_TRACKFLOW_API_BASE_URL`.

---

## Comandos de verificación

Todos se ejecutan desde la raíz del monorepo:

- **`npm run check:ts`** — tipos de `src/` (Hito 2).
- **`npm run typecheck:uis`** — `tsc --noEmit` en la web y el backoffice.
- **`npm run lint:uis`** — ESLint en la web y el backoffice.
- **`npm run build:uis`** — `next build` de ambas apps; detecta imports rotos hacia `src/`.
- **`npm run verify`** — todo lo anterior en orden. Es la puerta obligatoria antes de cada commit.
- **CLI de incidencias** — `python scripts/incidents-analyzer/analyze.py <fichero.csv>` desde la raíz.
- **API de incidencias** — instalar `services/api/requirements.txt` y ejecutar `uvicorn services.api.main:app --reload --port 8000`.
- **API completa** — `uv sync` y `uv run uvicorn services.api.main:app --reload --port 8000 --env-file .env`.
- **Tests de Python** — `uv run pytest` (o `uv run pytest --cov`) desde la raíz; detalle en `TESTING.md`.
- **Tests del backoffice** — `npm test` / `npm run test:coverage` en `uis/backoffice` (Jest).
- **Seed de incidencias** — `uv run python scripts/seed_incidents.py`.
- **Seed de carga (solo local)** — `uv run python scripts/seed_load_test.py --database-url sqlite:///<ruta> --incidents-db <ruta>`;
  rechaza URLs que no sean SQLite o PostgreSQL en `localhost`.
- **Latencia de la API** — `uv run python audit/caching/measure_api.py --email <e> --password <p> --label <nombre>`.
- **Seed de inventario** — `uv run --env-file .env python scripts/seed_inventory.py --user-email <usuario TinyDB>`.

---

## Restricciones técnicas

- **Tests automatizados** — pytest en `tests/` (config en `pyproject.toml`, `--import-mode=importlib`): `tests/auth` y
  `tests/backoffice` llaman a la lógica sin `TestClient`; `tests/http` conserva las pruebas de integración. `conftest.py`
  aísla cada test con TinyDB temporales vía `*_DB_PATH`. Jest en `uis/backoffice/__tests__` (entorno `node`, `ts-jest`).
  `npm run verify` sigue cubriendo tipos, lint y build de las UIs.
- **Contraseñas** — límite de bcrypt en **bytes** (72): `passwords.exceeds_bcrypt_limit` y el tipo `NewPassword` en la API,
  `lib/registration.ts` en el backoffice.
- **Errores de API** — la validación responde con `loc`, `msg` en español y `type`, nunca con `input` ni `ctx`
  (`services/api/errors.py`). Los 500 son genéricos y la traza solo va al log `trackflow.api`. Las llamadas externas se
  envuelven en una excepción propia sin datos personales (`EmailDeliveryError`).
- **Errores en la UI** — solo se muestran mensajes de `ApiError` (backoffice) o `RecordsApiError` (tracker), a través de
  `getUserMessage`; cualquier otro error usa un texto propio. Cada app tiene `error.tsx`, `global-error.tsx` (Next 16:
  `unstable_retry`) y `not-found.tsx`, que registran solo `error.digest`.
- **`src/` aislado** — no puede importar nada de `uis/` ni paquetes npm; debe compilar con el `tsconfig.json` raíz.
- **Imágenes remotas** — solo desde `images.unsplash.com` (`images.remotePatterns`). Next 16 solo permite `quality` 75 por defecto.
- **Windows** — tras instalar Node, `npm` y `node` pueden no estar en el PATH de las terminales ya abiertas: hay que reiniciarlas.
- **`node_modules/`** — la carpeta de la raíz estuvo versionada por error; desde el Hito 4 la ignora `.gitignore`.

---

_Documento interno — 4Geeks Academy · AI Engineering Track_
_Banco de memoria de TrackFlow Tech · Actualízalo cuando cambie el stack, una decisión, un puerto o un comando_
