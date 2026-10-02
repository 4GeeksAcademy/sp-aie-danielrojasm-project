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
- **`data/`** — pipelines de datos (`pipelines/`, con el pipeline semanal de desempeño de negocio en Prefect) y su lógica
  reutilizable (`process/`); `raw/` y `eval/` guardan salidas locales.
- **`services/reporting/`** — API `/reporting/*` del pipeline semanal, incluida por `services/api/main.py`.
- **`services/jobs/`** — estado de los jobs en segundo plano (`job_runs`); el job nocturno vive en `scripts/nightly_export.py` y lo
  dispara el contenedor `scheduler` (`infra/scheduler/`).
- **`services/tasks/`** — cola de tareas asíncronas (Celery + Redis): instancia, tarea del pipeline semanal y DLQ. El worker
  es el contenedor `worker`; Flower, el contenedor `flower`.
- **`mcps/trackflow_tools/`** — servidor MCP (FastMCP, Streamable HTTP, puerto 8001) con OAuth de MCP Auth: tickets del
  gestor de incidencias y consulta del inventario. `infra/keycloak/` guarda el realm de su proveedor OAuth.
- **`agents/`, `skills/`, `workflows/`** — espacio para el producto de hitos futuros (agentes de la empresa, no del IDE).
  Solo contienen la plantilla.

---

## Stack

### ⚙️ Runtime y lógica de negocio

**Node.js:** 24.x LTS (instalado con winget en la máquina de desarrollo)

**TypeScript en la raíz:** `typescript ^6.0.3`. El `tsconfig.json` raíz es `strict`, usa `moduleResolution: Bundler` y solo incluye
`src/**/*.ts`.

**Python:** el CLI y `services/api/incidents_analyzer.py` usan la biblioteca estándar para validar y agregar el CSV en streaming. El analizador y el seed validan con `packages/shared/incidents/csv_validation.py`. La API usa
FastAPI, `python-multipart` y Uvicorn, declarados en `services/api/requirements.txt`; el reporte de telemetría usa Pandas, y el pipeline semanal
de `data/pipelines/`, Pandas y Prefect 3. El modelo de pronóstico de ventas usa scikit-learn, SciPy y matplotlib. El RAG usa `qdrant-client` y `openai`.

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

### Telemetría: captura y almacenamiento — Milestone 09

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
  `/app/docs/telemetry`) y solo emite eventos cuyo emisor incluye `api`. Sumideros en `SINKS`: el log `trackflow.telemetry` y
  `telemetry_storage.api_event_buffer`, que `timing_middleware` vacía con un bulk insert tras enviar cada respuesta (y el `lifespan`
  al apagar). `TELEMETRY_ENDPOINT`, `TELEMETRY_ENVIRONMENT`, `TELEMETRY_HASH_KEY` (HMAC del email) y `STOCK_MIN_THRESHOLDS`.
- **Almacén (`telemetry_storage.py`):** tabla `telemetry_events` de solo escritura (trigger contra UPDATE/DELETE, RLS sin políticas).
  `id` = `eventId` para que un reintento no duplique; `service` = `source`; `tags` = `properties` ya filtrado. No se persisten
  `requestId`, `schemaVersion` ni `environment` (siguen en el log); cada entorno usa su propio proyecto de Supabase.
- **Ingesta (`routes/telemetry.py`):** lee el sobre de forma laxa (`TelemetryIngestEnvelope`, `events: list[Any]`) y valida cada evento
  con `TelemetryEvent.model_validate`: un evento malo se cuenta en `rejected` y no tumba el lote. Solo acepta emisor `backoffice` y
  `event_type` cuyo emisor lo incluya (los obligatorios no se pueden suplantar desde el navegador). 503 si no hay almacén.
- **Inventario:** nueva tabla `inventory_counts` (la crea `create_all`, no modifica tablas existentes) y rutas 405 explícitas contra
  la edición directa del stock. Las 12 rutas 405 declaran su esquema de error; `tests/http/test_serialization.py` las cuenta aparte.
- **Restricciones abiertas:** sin outbox, un evento obligatorio se pierde si el proceso cae entre el `commit` y el log. El umbral se
  dispara comparando stock anterior y resultante en la salida; una recepción concurrente no bloquea la fila del SKU, así que en una
  carrera `stock_after` puede quedar desfasado hasta que exista `stock_threshold_alerts`. La ingesta no exige token ni toma
  `userId` del JWT: cualquiera que alcance la API puede escribir eventos de navegador (no los de la API).

### Reporte técnico de telemetría — Milestone 09

`services/telemetry/analysis.py` (paquete fuera de `services/api`, importado como `services.telemetry.analysis`) concentra el
pipeline con Pandas: cinco funciones puras `(bind, start, end) -> list[dict]` que cargan con SQLAlchemy Core solo las columnas y
los `event_type` necesarios dentro de `[start, end)`, extraen campos de `tags` en Pandas, convierten `timestamp` con
`pd.to_datetime(utc=True)` antes de agrupar y devuelven tipos nativos (`NaN` → `None`). Días en UTC. `build_report` las ejecuta
en una sola conexión. Es un reporte técnico: las métricas de negocio quedan para el hito de pipelines de datos.

- **Endpoint:** `GET /telemetry/report` (`routes/telemetry_report.py`, bearer) resuelve el período una vez (7 días por defecto,
  máximo 90, `start >= end` → 422) y sirve `TelemetryReport` (`telemetry_report_models.py`). `report_cache` (`TTLCache`, 60 s)
  usa como clave los parámetros recibidos: la petición sin parámetros es `(None, None)` y reutiliza el período calculado. No se
  invalida al ingerir; el TTL es el retraso máximo.
- **Fallos:** `ERROR_EVENT_TYPES` clasifica los eventos de fallo en `system` (5xx, caídas, errores de cliente) y `rejected`
  (login, validación, reglas de inventario). La latencia es la de Web Vitals (`page_load_recorded`, p75), porque
  `api_latency_recorded` aún no se emite.
- **Backoffice:** `/telemetry` (`components/telemetry/TelemetryReportView.tsx`) consume el reporte desde `lib/telemetry-report.ts`
  con `useApiList` (lista de un elemento) y barras CSS, sin librería de gráficos. `/telemetry` no tiene `section` en el
  esquema de telemetría, así que no emite `page_viewed`.
- **Dependencia:** `pandas` en `pyproject.toml` y `services/api/requirements.txt` (imagen Docker).

### Pipeline de desempeño de negocio — Milestone 09

Diseño e implementación en `data/pipelines/PIPELINE_DESIGN.md` (sección 16: comandos y diferencias con el diseño; sección 17:
subflows, tests y dashboard).

- **Código:** `data/pipelines/pipeline.py` (flow principal, subflows, tasks, CLI y `--serve`),
  `data/pipelines/weekly_warehouse_client_performance/` (`schema.py`, `database.py`, `storage.py`, `runs.py`, `queries.py`) y
  `data/process/weekly_performance.py` (Pandas puro: una función por KPI más `clean_business_events` y `assemble_weekly_rows`).
- **Subflows:** el flow principal solo abre/cierra la corrida y llama a extracción, transformación, carga y a los opcionales de
  reconciliación y snapshot (`return_state=True`). Se pasan DataFrames entre subflows: los parámetros no se guardan en el servidor de
  Prefect, solo en memoria del proceso. Los tests parchean las tasks como atributos del módulo, así que los subflows las buscan
  por nombre en `pipeline` en cada llamada.
  `data/`, `data/pipelines/` y `data/process/` son paquetes Python; `pipeline.py` añade la raíz a `sys.path` para poder
  ejecutarse como script. El pipeline no importa nada de `services/` (motor propio desde `DATABASE_URL`, tablas fuente con
  `table()`); `services/reporting/` sí importa de `data/pipelines/`.
- **Prefect 3** (`prefect>=3`, `python-dotenv`): sin `PREFECT_API_URL` levanta un servidor temporal por proceso (~10 s).
  `PREFECT_LOCAL_STORAGE_PATH` apunta a `data/raw/weekly_warehouse_client_performance/prefect-results` (ignorado por git); los
  snapshots de eval van a `data/eval/weekly_warehouse_client_performance/` (ignorado). Los blocks JSON y Secret son opcionales.
- **API:** `POST /reporting/pipeline-runs` (admin) reserva la corrida `pending` y encola la tarea de Celery
  `reporting.run_weekly_performance`; el flow corre en el worker, nunca en la API (ver "Cola de tareas asíncronas").
- **Tests:** `tests/reporting` usa SQLite con `reporting` adjunto (`ATTACH`) y `prefect_test_harness` (sesión). Las fixtures
  vacían `services.api.database.get_engine.cache_clear()`: la API cachea su motor al volcar eventos de telemetría.
  `tests/pipelines/test_pipeline.py` prueba las tasks con `task.fn` y DataFrames en memoria (sin BD ni Prefect).
- **Dashboard:** `uis/backoffice/app/reporting` + `lib/reporting.ts` por el rewrite `/api/reporting/*`. Un 404 de la API es estado
  vacío (semana sin calcular), no error. En SQLite, `services.api.database.get_engine` no adjunta `reporting`: para probar la API
  en local con SQLite hay que usar `engine_for` del pipeline; en Supabase no hace falta.
- **Docker:** la imagen instala Prefect y `docker-compose.yml` monta `./data` en `/app/data`.

Decisiones del diseño que se mantienen:

- **Separación:** el pipeline lee `telemetry_events` en solo lectura y escribe solo en el esquema `reporting`
  (`weekly_warehouse_client_performance`, `pipeline_runs`, `pipeline_run_weeks`). El DDL va en un `schema.sql` propio porque
  `create_all` no crea esquemas ni índices parciales. API en `services/reporting/`, que importa de `data/pipelines/` (nunca al revés).
- **Cálculo:** semana ISO en UTC por `timestamp`; `outbound_orders_count` solo cuenta `exit_type = 'dispatch'`; dedup por `id` y por
  clave de negocio (`order_id`, `count_id`); nunca se calcula la semana en curso.
- **Idempotencia:** recalcular semanas completas (última cerrada + 3 de lookback + las que tengan `received_at` posterior al
  watermark) y upsert por `unique (warehouse, client_id, week_start)`, una transacción por semana.
- **Concurrencia:** índice único parcial en `pipeline_runs` (una corrida activa por pipeline) más límite de concurrencia de Prefect.
- **Prefect:** cron `0 2 * * 1` UTC (`--serve`, `global_limit=1`); blocks `Secret` (`DATABASE_URL`) y `JSON` (umbrales) opcionales.

### Job nocturno de telemetría — Milestone 09 (Ticket #DEV-53)

- **Código:** `scripts/nightly_export.py` (fecha objetivo, CSV, subproceso del pipeline, CLI) y `services/jobs/job_runner.py`
  (tabla `job_runs`, transiciones y `run_job`). DDL equivalente en `services/jobs/migrations/001_create_job_runs.sql`.
- **Proceso independiente:** ni el script ni `services/jobs` importan FastAPI ni `services/api` (lo comprueba un test). Motor propio
  desde `DATABASE_URL`; `telemetry_events` se lee con una `Table` mínima. Nada de `APScheduler`, `BackgroundTasks` ni lifespan.
- **`job_runs` ≠ `pipeline_runs`:** `job_runs` (esquema `public`) es la orquestación: CSV, disparo, lock e idempotencia por día.
  `reporting.pipeline_runs` sigue registrando las fases del ETL. El pipeline se lanza con
  `python -m data.pipelines.pipeline --triggered-by job:nightly_export` (no existe `--no-prefect`): recalcula la última semana
  cerrada + 3 de lookback + semanas con eventos tardíos. Cada noche es redundante pero idempotente (upsert sin cambios).
- **Lock:** la fila `processing` es el lock; el índice único parcial `job_runs_one_active` (una fila `pending`/`processing` por job)
  hace atómica la toma cuando dos instancias arrancan a la vez. Filas activas de más de 6 h caducan a `failed` (proceso muerto con
  SIGKILL). SIGTERM se convierte en `SystemExit` para que el `finally` cierre la fila.
- **Idempotencia:** `completed` por `(job_name, target_date)` → se omite. El CSV se escribe en `.partial` y se renombra: un fallo a
  medias no deja un archivo que la siguiente ejecución dé por bueno. `TARGET_DATE` de hoy o futuro se rechaza (CSV incompleto).
- **CSV:** `data/raw/telemetry_YYYY-MM-DD.csv` (ignorado por git: lleva `user_id` y `session_id`), filas por `timestamp` en el día
  UTC, `tags` como JSON con claves ordenadas. Los eventos que lleguen tarde no entran en el CSV del día; el pipeline sí los ve.
- **Disparador:** contenedor `scheduler` (`infra/scheduler/Dockerfile`, supercronic v0.2.49 linux-amd64 con SHA1 verificado),
  `15 1 * * *` UTC. Supercronic hereda `env_file`, escribe en la salida del contenedor y no solapa ejecuciones; el lock de BD cubre
  además ejecuciones manuales y otros hosts. Monta `services/`, `scripts/` (solo lectura), `data/` y el crontab.
- **Logs:** logger `trackflow.jobs` a stdout en UTF-8, `<ISO UTC> <nivel> trackflow.jobs job=… target_date=… status=… <mensaje>`;
  el ERROR lleva la traza. `error_message` en BD solo guarda clase y primera línea, sin URLs ni SQL.
- **Tests:** `tests/jobs` con SQLite temporal y un subproceso falso en lugar del pipeline (sin Prefect).

### Cola de tareas asíncronas (Celery + Redis) — Milestone 09 (Ticket #DEV-55)

- **Código:** `services/tasks/` (`celery_app.py`, `pipeline.py`, `dead_letter.py`); `GET /tasks/{task_id}` en
  `services/api/routes/tasks.py` (`TaskStatusRead`). Detalle y comandos en `services/tasks/README.md`.
- **Productor / consumidor:** la API solo encola (`apply_async(..., retry=False)`); el worker es otro proceso (contenedor
  `worker`, colas `default` y `dead_letter`). `services/tasks` no importa FastAPI ni `services/api` (lo comprueba un test).
- **Redis:** broker y result backend (`REDIS_URL`; en Compose, `DOCKER_REDIS_URL`). `redis:7-alpine` con `noeviction` y AOF,
  publicado solo en `127.0.0.1:6379`. En Windows hay que usar `127.0.0.1`: con `localhost` cada conexión nueva tarda ~2 s
  (prueba antes IPv6).
- **Operación convertida:** `POST /reporting/pipeline-runs`. Mensaje = `[run_id, week_start | null, triggered_by]` (142 bytes).
  `PipelineRunTriggered` añade `task_id`. Sin Redis: `503` y la corrida se cierra `failed` (no deja el lock tomado); la API
  se recupera sola cuando vuelve Redis. El backend es `PublishOnlyRedisBackend` (`on_task_call` vacío): la suscripción
  pub/sub por tarea del backend de Redis colgaba `apply_async` más de 60 s con Redis caído y acababa en `RuntimeError`.
- **Configuración:** JSON, `task_track_started`, `task_acks_late` + `task_reject_on_worker_lost`, `prefetch = 1`, límites
  20/25 min en el pipeline (30 min por defecto), `visibility_timeout` 2 h, `result_expires` 24 h y eventos activados para Flower.
- **Reintentos:** `max_retries = 3` (4 intentos), backoff `TASKS_RETRY_BACKOFF_SECONDS × 2^n` (30/60/120 s). Cada intento
  fallido cierra su corrida `failed`; el reintento reserva otra (`retry_of` la enlaza). Se reintenta cualquier fallo: las
  tasks de Prefect ya filtran internamente los transitorios.
- **DLQ:** al agotar los reintentos se publica `tasks.record_dead_letter` en la cola `dead_letter`, que inserta en
  `task_dead_letters` (`public`, `task_id` único, RLS sin políticas; SQL en `services/tasks/migrations/`). Si no se puede
  publicar, se escribe directamente; si tampoco, log `CRITICAL`.
- **Estados:** `PENDING/RECEIVED` → `pending`, `STARTED` → `started`, `RETRY` → `retry`, `SUCCESS` → `success`,
  `FAILURE/REVOKED` → `failure`. Un id desconocido sale `pending`. El error se sanea con `job_runner.describe_error`.
- **Logs:** `trackflow.tasks`, señales `task_prerun`/`task_postrun`: `task_id=… task=… attempt=… status=… duration_ms=…`;
  `retry` en WARNING y `failure` en ERROR con traza.
- **Latencia del 202:** `ensure_schema` se recuerda por motor y proceso (`WeakSet`): el DDL de `reporting` costaba ~1,3 s por
  disparo contra Supabase. Con Postgres local el 202 tarda 15–27 ms. Contra Supabase desde la máquina de desarrollo, ~480 ms:
  son ~4 idas y vueltas a ~120 ms (la reserva de la corrida es síncrona porque el `409` depende de ella).
- **Demo:** `TASKS_SIMULATE_FAILURE=1` en el worker hace fallar el pipeline antes del flow (el worker lo avisa al arrancar).
- **Windows sin Docker:** `celery ... worker --pool=solo` (prefork no funciona en Windows; tampoco los límites de tiempo).
- **Tests:** `tests/tasks` con Celery en modo eager (`.apply()` recorre la cadena de reintentos en el acto) y SQLite.

### Pronóstico de ingresos mensuales — Milestone 09

- **Código:** `data/process/sales_forecast.py` (datos y features), `data/process/forecast_metrics.py` (métricas) y
  `scripts/train_sales_forecast.py` (entrenamiento, evaluación y gráfico). Detalle en `data/eval/sales_forecast/README.md`.
- **Split:** por año natural, 8 años de entrenamiento y 2 de prueba; `split_train_test` falla si los años no están completos o no son 10.
  Los nulos se imputan después del split y solo en entrenamiento.
- **Target normalizado:** `revenue_t / media de los 12 meses previos`. Los árboles no extrapolan la tendencia (~6 % anual) y la
  prueba queda por encima del rango de entrenamiento; predecir euros directamente subestima todo 2024–2025.
- **Sin fuga:** features solo con meses anteriores (24 meses de historia mínima → 72 filas de entrenamiento); `shipments_processed` y
  `avg_revenue_per_shipment_eur` no se usan porque son contemporáneas al ingreso. La evaluación es recursiva desde 2023-12.
- **Random Forest** (500 árboles, `min_samples_leaf=2`, `random_state=42`) en vez de XGBoost: pocos datos, explicabilidad para Finanzas
  y banda de variabilidad a partir de las trayectorias por árbol.
- **PSI:** bins por cuantiles de la referencia con al menos 6 valores por bin (4 con 24 meses) y suavizado +0,5; con muestras tan
  pequeñas el valor depende del número de bins.
- **K2 Score:** se interpreta como R² (`r2_score`); se reporta además el K² de D'Agostino sobre los residuos.
- **Validación cruzada:** `data/process/forecast_validation.py`, solo sobre 2016–2023. `TimeSeriesSplit(5, test_size=12)`, con
  ventana creciente y un año natural por fold (2019…2023). `assert_chronological` falla si un fold baraja, solapa o retrocede.
  Cada fold reconstruye las features solo con sus meses (no se calculan sobre la serie completa). Se valida a un paso, para
  compararlo con el error de entrenamiento, y en recursivo de 12 meses, que es el uso real.
- **Métrica principal: RMSE** (raíz del MSE que pide Dirección); penaliza los fallos grandes en los picos de noviembre–diciembre. El
  MAE es secundario y el sesgo con signo se reporta aparte (`real − pronóstico`, negativo = sobreestima).
- **Diagnóstico:** bien ajustado; regularizar empeora la validación. Error residual = sesgo del nivel anual por el crecimiento
  alterno (~3 %/~9 %). Acción propuesta, aún no implementada: separar el crecimiento anual del bosque
  (`alternating_growth_adjustment`). Detalle en `data/eval/evaluation_report.md`.

### RAG y base de conocimiento comercial — Milestone 09

Diseño completo en `docs/rag/rag-design.md`.

- **Código:** `data/process/rag.py` (`setup`, `embed`, chunking, clientes y configuración) y `data/pipelines/rag.py`
  (`retrieve`, `search_chunks`, `build_messages`, `generate_answer`, `query`). `services/api/routes/knowledge.py` solo llama a
  `query()`; la UI está en `uis/backoffice/app/knowledge` + `lib/knowledge.ts` (rewrite `/api/knowledge/*`).
- **Sin frameworks de orquestación:** SDK `qdrant-client` y SDK `openai` contra el gateway de 4Geeks (compatible con OpenAI).
  Variables en el `.env` raíz: `LLM_API_URL` (con `/v1`), `LLM_API_KEY`, `LLM_EMBEDDING_MODEL`, `LLM_GENERATION_MODEL`
  (tienen que ser distintos; si no, `RagConfigurationError`), `QDRANT_URL` (`DOCKER_QDRANT_URL` en Compose) y, opcional,
  `RAG_MIN_SCORE`.
- **Qdrant:** colección `trackflow_knowledge` (nombre del CONTEXT), coseno, dimensión leída del primer vector (1024 con
  `pplx-embed-v1-0.6b`). Payload: `company`, `source_document`, `section`, `language`, `chunk_index`, `text`.
- **Idempotencia:** `setup()` embebe todo y solo después recrea la colección; IDs `uuid5` por documento, idioma y `chunk_index`.
- **Contrato del cliente:** `{ "answer" }` y nada más. Scores y fuentes solo en el log `trackflow.rag`. 503 con mensaje propio si
  Qdrant, la colección o el gateway fallan.
- **Umbral:** `min_score = 0,40`, afinado con `scripts/evaluate_rag_retrieval.py`. No separa preguntas cercanas al corpus sin
  respuesta: eso queda en manos del prompt.
- **Reutilización:** el agente LangGraph llama a `retrieve()` y `generate_answer()` como nodos separados.

### Agente de soporte con LangGraph — Milestone 09

Detalle en `services/support_agent/README.md`.

- **Stack:** `langgraph` 1.2 (en `pyproject.toml` y `services/api/requirements.txt`). El router se monta en la API
  principal; `/knowledge/query` sigue igual.
- **Estado mínimo:** `question`, `route`, `tickets`, `context`, `answer`, `error`. Sin historial de conversación.
- **Fuentes:** RAG (políticas estables) y la tool `get_ticket` (gestor de incidencias en vivo, nunca indexado en
  Qdrant). Decide `route_question` con el modelo de generación en modo JSON; solo acepta tickets escritos en la
  pregunta y, si el modelo falla, aplica reglas.
- **Tool de tickets:** cliente del servidor MCP. Carga solo `get_ticket_status` con `langchain-mcp-adapters` (en
  `pyproject.toml` y `services/api/requirements.txt`) y se autentica con un token `client_credentials` del cliente
  `support-agent` (solo `incidents:read`). Timeout de 4 s. Ya no existe la llamada HTTP directa al gestor. Los fallos
  son resultados (`not_found`, `timeout`, `unavailable`) que llevan al nodo `ticket_fallback`; un ticket sin confirmar
  no llega nunca al modelo. La fuente sigue llamándose `incidents_tool` en el trace.
- **Compilación:** al importar `services/support_agent/graph.py`. LangGraph no detecta nodos huérfanos ni sin salida
  (su grafo dibujable une a END cualquier nodo sin aristas), así que `compile_graph()` lo valida sobre las aristas
  declaradas; las aristas condicionales necesitan su `path_map` explícito.
- **Checkpointing:** `InMemorySaver`, `thread_id` = `run_id`. Las corridas completadas liberan el hilo; las fallidas lo
  conservan para `resume_run()`. No sobrevive a un reinicio del proceso.
- **Trace:** JSON por corrida en `AGENT_TRACE_DIR` (por defecto `data/raw/agent_traces/`, ignorado por git; los tests lo
  apuntan a un temporal en `tests/conftest.py`). Sin LangSmith.
- **Evals:** se ejecutan contra traces grabados (`data/eval/agent/traces/`), no contra Qdrant ni el gateway.
- **Memoria:** ver "Memoria del agente de soporte". El estado añade `message`, `conversation_id`, `user_id`, `run_id`
  y los campos de memoria; el trace pasa a `trace_version` 3 (`agent_memory` en `sources_used` solo si recordó algo).

### Memoria del agente de soporte — Milestone 09 (Ticket #MEM-092)

Diseño, prohibiciones y evidencias en `docs/agent-memory/memory-design.md`.

- **Almacén:** Redis (`REDIS_URL`, el mismo de Celery, con AOF y `noeviction`) con prefijo `trackflow:agent_memory`:
  hash `:entries` (una entrada por sujeto), hash `:pending` (una propuesta por usuario) y stream `:audit` (solo se
  añade, sin recortar). Nunca se escribe en Qdrant ni en `trackflow_knowledge`. Cliente `redis` (`pyproject.toml` y
  `services/api/requirements.txt`) con timeouts de 1–2 s; cualquier fallo es `MemoryUnavailableError` y el agente
  responde avisando de que no puede recordar.
- **Flujo:** propuesta → decisión explícita del usuario en el turno siguiente de la misma conversación → consolidación.
  Sin `user_id` no se propone nada (scripts). El clasificador y la generación usan el modelo de generación en modo JSON.
- **Política en código (`memory/policy.py`):** categorías `carrier_rule`, `incident_context`, `client_preference`;
  transportistas y países de la base de conocimiento; patrones prohibidos; cita del usuario (≥ 80 % de sus palabras en
  el mensaje). Lo bloqueado y los mensajes del registro se guardan redactados (`redact`).
- **Tests:** `tests/conftest.py` da a cada test un `fakeredis` (dependencia de desarrollo); nunca toca `REDIS_URL`.
  Los scripts de grabación usan sus propios espacios de nombres (`:eval`, `:evidence`) y los vacían.

### Servidor MCP de herramientas — Milestone 09

Detalle en `mcps/trackflow_tools/README.md`.

- **Stack:** `fastmcp` 3.4 (`>=3.4,<4`: FastMCP 4 trae `mcp` 2.x y `langchain-mcp-adapters` exige `mcp<2`),
  `mcpauth==0.2.0b1` (la primera versión con Protected Resource Metadata; la 0.1.1 estable no la tiene) y Keycloak
  26.4 en Compose como proveedor OIDC. La auth integrada de FastMCP no se usa.
- **Transporte:** Streamable HTTP stateless con respuestas JSON. Varios clientes remotos y bearer por petición; el
  `AuthInfo` de MCP Auth (contextvar) es siempre el de esa petición.
- **OAuth:** resource server. Valida firma (JWKS), issuer exacto, audiencia `trackflow-mcp` y expiración; sin token
  válido responde 401 antes de `tools/list`. Scopes por tool (`incidents:read`, `incidents:write`, `inventory:read`),
  comprobados en un middleware de FastMCP; no hay scope de escritura de inventario. Realm versionado en
  `infra/keycloak/trackflow-realm.json` (se reimporta en cada arranque, sin volumen) con los clientes `support-agent`
  y `trackflow-operator`; los secretos van en el `.env`.
- **Backend:** la API de TrackFlow por HTTP, con un JWT HS256 de 5 min para `MCP_SERVICE_USER_ID`. Los cambios de
  estado pasan por `PATCH /api/incidents/{id}/status`. El inventario solo admite `GET /inventory/*`
  (`InventoryReader`) y las escrituras se rechazan con `INVENTORY_READ_ONLY`.
- **Errores y logs:** códigos `INSUFFICIENT_SCOPE`, `INVENTORY_READ_ONLY`, `VALIDATION_ERROR`, `NOT_FOUND` y
  `UPSTREAM_UNAVAILABLE`; un log `trackflow.mcp` por invocación (tool, client, subject, resultado). Códigos de salida:
  2 sin configuración, 3 issuer inaccesible.
- **Restricción:** MCP Auth descarga el JWKS en cada petición. Con `localhost`, Windows prueba antes `::1` y cada
  validación tarda ~2 s, así que las URLs locales usan `127.0.0.1`.

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

`docker compose up` desde la raíz levanta nueve servicios en la red `trackflow-dev` (`redis`, `worker` y `flower` se
describen en "Cola de tareas asíncronas"; `worker` y `flower` usan la imagen de `services/Dockerfile` con otro `command`):

- **`api`** (`services/Dockerfile`, `python:3.12-slim` + `uv pip install --system -r api/requirements.txt`): Uvicorn con
  `--reload` sobre `services/` y `packages/`, montados por bind mount desde `/app`, porque la API se importa como
  `services.api.main` y usa `packages.shared`. Recibe `.env` entero (`env_file`). `BACKOFFICE_ORIGIN` y `PASSWORD_RESET_URL`
  se sobrescriben con `DOCKER_BACKOFFICE_ORIGIN` y `DOCKER_PASSWORD_RESET_URL`, porque en el contenedor el backoffice va en el
  3001 y en local sigue en el 3002. `REDIS_URL` se sobrescribe con `DOCKER_REDIS_URL`. Healthcheck contra `GET /`.
- **`scheduler`** (`infra/scheduler/Dockerfile`): supercronic con `infra/scheduler/crontab`; ejecuta los jobs nocturnos fuera
  de la API. Ver "Job nocturno de telemetría".
- **`uis`** (`uis/Dockerfile`, `node:24-alpine`): `npm ci` por separado en website y backoffice; `uis/start.sh` arranca
  `next dev` de la web en el 3000 y del backoffice en el 3001, y sale si una de las dos cae. Monta `uis/`, más `src/` y el
  `tsconfig.json` raíz (solo lectura) para que `turbopack.root` (= `/app`) resuelva `@trackflow/logic`. `node_modules` y `.next`
  de cada app van en volúmenes anónimos: los binarios son de Alpine, no del host. Solo recibe `TRACKFLOW_API_INTERNAL_URL` y
  `NEXT_PUBLIC_INVENTORY_API_URL` (`http://api:8000`, por nombre de servicio), nunca los secretos de la API. Estas variables del
  proceso tienen prioridad sobre `uis/backoffice/.env.local`, que también llega por el bind mount.
- Todas las variables salen de `.env` (plantilla en `.env.example`); el YAML falla con mensaje (`${VAR:?}`) si falta alguna.
- Tras cambiar un `package.json` o `requirements.txt`: `docker compose up --build -V` (renueva los volúmenes anónimos).
- `talent-pipeline-tracker` no está en el contenedor de interfaces.
- **`keycloak`** y **`mcp`**: proveedor OAuth y servidor MCP (`mcps/trackflow_tools/Dockerfile`, contexto en la raíz, deps de
  `services/api/requirements.txt` + `mcps/trackflow_tools/requirements.txt`; código por bind mount de solo lectura). `mcp` espera a
  `keycloak` y `api` sanos (healthcheck de Keycloak en `/health/ready` del 9000) y no convive con el servidor del host (8001).
  `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`: el issuer de los tokens es siempre `KEYCLOAK_URL`, pero el token endpoint y el JWKS del
  discovery usan el host de la petición. Así `mcp` y el agente de `api` descargan el discovery de `keycloak:8080`
  (`DOCKER_MCP_OAUTH_ISSUER`) y aceptan o piden tokens con el mismo `iss` que los del host. `api` recibe además
  `MCP_SERVER_URL=DOCKER_MCP_SERVER_URL` (`http://mcp:8001/mcp`).
- **Codespaces:** el Docker-in-Docker del Codespace arrastra una tabla `iptables-legacy` con `FORWARD DROP` que solo acepta
  `docker0`; en una red con nombre (`br-*`) los contenedores no se ven entre sí ni salen a internet (el DNS interno sí resuelve).
  No ocurre en Docker Desktop ni en un Docker Engine estándar.
  Reglas manuales (no persisten): `-i <br> ! -o <br>` + `RELATED,ESTABLISHED` + `MASQUERADE` para la salida a internet y
  `-i <br> -o <br>` para el tráfico entre contenedores, en `iptables-legacy` FORWARD/POSTROUTING.

---

## Puertos de desarrollo

- **`uis/website`** — puerto **3000**, con `npm run dev` o `npm run dev:website` desde la raíz.
- **`uis/backoffice`** — puerto **3002**, con `npm run dev` o `npm run dev:backoffice` desde la raíz.
- **`services/api`** — puerto **8000**, con `uvicorn services.api.main:app --reload --port 8000` desde la raíz.
- **`uis/talent-pipeline-tracker`** — puerto 3000 por defecto, que choca con la web. Se arranca con `npm run dev -- --port 3003`.
- **Redis** — puerto **6379** (solo `127.0.0.1`), con `docker compose up -d redis`.
- **Flower** — puerto **5555** (solo `127.0.0.1`), con `docker compose up -d flower`.
- **Qdrant** — puerto **6333** (solo `127.0.0.1`), con `docker compose up -d qdrant`.
- **Servidor MCP** — puerto **8001**, con `docker compose up -d mcp` o `uv run --env-file .env python -m mcps.trackflow_tools` (uno u otro).
- **Keycloak** — puerto **8080** (solo `127.0.0.1`), con `docker compose up -d keycloak`.

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
- **Pipeline semanal** — `uv run python data/pipelines/pipeline.py` (`--week-start YYYY-MM-DD`, `--lookback-weeks N`, `--serve`).
- **Pronóstico de ventas** — `uv run python scripts/train_sales_forecast.py` (escribe `data/eval/sales_forecast/`).
- **Evaluación del pronóstico** — `uv run python scripts/evaluate_sales_forecast.py` (CV temporal y curva de aprendizaje en `data/eval/`).
- **Base de conocimiento (RAG)** — `uv run python -m data.process.rag` indexa `docs/company-knowledge-base/` en Qdrant;
  `uv run python scripts/evaluate_rag_retrieval.py` mide Recall@3 (`data/eval/rag/retrieval_report.json`).
- **Evals del agente LangGraph** — `uv run python scripts/record_agent_traces.py` graba los traces (Qdrant, `.env`,
  Keycloak, la API y el servidor MCP en `MCP_SERVER_URL`);
  `uv run pytest tests/pipelines/test_agent_evals.py -v` los evalúa.
- **Evidencia de la memoria del agente** — `uv run python scripts/record_memory_evidence.py` (gateway, Qdrant y Redis);
  `uv run pytest tests/pipelines/test_agent_memory_evals.py -v` la evalúa.
- **Servidor MCP** — `docker compose up -d keycloak api mcp`, o `docker compose up -d keycloak api` y
  `uv run --env-file .env python -m mcps.trackflow_tools`;
  `uv run pytest tests/mcp -v`.
- **Job nocturno** — `uv run python scripts/nightly_export.py` (`TARGET_DATE=YYYY-MM-DD` para otra fecha cerrada).
- **Worker de Celery** — `docker compose up -d redis worker flower` / `docker compose stop worker`; sin Docker,
  `uv run --env-file .env celery -A services.tasks.celery_app worker --loglevel=INFO --queues=default,dead_letter`
  (`--pool=solo` en Windows).
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
