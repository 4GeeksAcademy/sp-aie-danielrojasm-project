# Progreso de TrackFlow Tech

## AI Engineering · 4Geeks Academy — Banco de memoria: estado del desarrollo

---

Este es el registro vivo del proyecto: qué funciona, qué problemas conocemos y qué viene después. Cada cambio relevante (una feature, una
decisión o un problema nuevo) añade una entrada al principio del **Historial**. No es un roadmap de marketing.


### Auditoría de rendimiento frontend — medición inicial

- Línea base con Lighthouse 12 CLI (build de producción,
   Chromium headless, 3 corridas y mediana; móvil y desktop) en website `/`
   y `/aplicar` y backoffice `/` e `/inventory/products` con sesión. JSON y
   PNG en `audit/before/lighthouse/`; script en `audit/lighthouse-runner.mjs`.
- Desktop: Performance 100 en las cuatro vistas. Móvil: website 96/92,
   backoffice 98/94. LCP móvil de la home: 2,7 s simulado, pero 1,7 s con
   throttling real (`THROTTLING=devtools`); quitar el preload del hero no
   mejora y rompe desktop, así que se mantiene y solo se migra `priority` →
   `preload` (deprecación de Next 16). Accesibilidad 91–96 con fallos WCAG.
- `audit/AUDIT.md` recoge causas raíz y dos refactors: hook `useApiResource`
   (backoffice) y `ErrorFallback` por app. Evidencia del experimento del
   hero en `audit/experiments/p1-hero-preload/`.
- Siguiente paso: extraer `useApiResource` y estabilizar la carga del
   inventario (CLS 0,03).

### Hito 5 — Contenedorización del monorepo (#infra-40)

- `uis/Dockerfile` + `uis/start.sh` (website :3000 y backoffice
   :3001 en un único contenedor), `services/Dockerfile` (FastAPI con
   `--reload`), `.dockerignore` en ambas carpetas y `docker-compose.yml` con la
   red `trackflow-dev`. Variables nuevas en `.env.example`
   (`TRACKFLOW_API_INTERNAL_URL`, `NEXT_PUBLIC_INVENTORY_API_URL`,
   `DOCKER_BACKOFFICE_ORIGIN`, `DOCKER_PASSWORD_RESET_URL`).
- Verificado en Codespaces: `docker compose build` y `up -d` sin errores; `api`
   healthy; `/`, `/aplicar` (3000), `/`, `/login`, `/inventory/products` (3001)
   y `GET /` de la API (8000) → 200. Recarga en caliente comprobada editando
   `site.ts` y `main.py` sin reconstruir. `api` resuelve por DNS desde `uis`.
- Bloqueo: en este Codespace la red `trackflow-dev` no reenvía tráfico
   (`iptables-legacy` con `FORWARD DROP`, ver techContext), así que los
   rewrites `uis → api:8000` agotan el tiempo y Google Fonts/Unsplash fallan.
- Siguiente paso: permitir los bridges `br-*` en la tabla legacy del Codespace
   (o probar en Docker Desktop) y verificar login e inventario vía rewrite.

### Hito 5 — Backoffice: interfaz de inventario (TRK-0341)

- Cuatro vistas en `uis/backoffice`: `/inventory/products` (stock
   por SKU con nivel saludable ≥ 50 / bajo 1–49 / sin stock 0 y enlaces de
   entrada/salida por fila), `/inventory/orders/inbound`,
   `/inventory/orders/outbound` (stock del SKU consultado al seleccionarlo,
   aviso si la cantidad lo supera y el 400 de la API junto a la cantidad) y
   `/inventory/orders` (historial de solo lectura con tipo, SKU, fecha y
   `user_uuid`). `/inventory` redirige al stock.
- `lib/inventory.ts` concentra las llamadas; pasan por `requestJson`
   (Bearer y 401 → `/login`) y el rewrite `/api/inventory/*`, que usa
   `NEXT_PUBLIC_INVENTORY_API_URL` o el origen de la API.
- Verificado: `npm run verify` exit 0, Jest 53 (13 nuevos), Playwright
   contra la API real: las cuatro rutas sin sesión → `/login`; stock
   reactivo (40 → 165 al cambiar de SKU); aviso con 41 sobre 40; 400 inline;
   entrada y salida correctas con confirmación y formulario limpio; historial
   y tabla actualizados; sin errores de consola.
- Supabase conserva, por decisión del equipo, dos movimientos de esa prueba
   en TEC-CHG-065 (ZGZ): entrada id 8 (+25) y salida id 5 (−10). El stock es
   55 (no 40) y el historial tiene 13 órdenes (no 11).

### Hito 5 — Inventario con ORM y doble base de datos (TRK-0341)

- `/inventory` en `services/api`: SKUs, recepciones y salidas en Supabase con
   SQLModel; auth sigue en TinyDB y cada movimiento guarda su `user_uuid`.
- Stock calculado por SKU y almacén (nunca almacenado); salida sin stock
   suficiente → 400 sin escribir; `dispatch` sin `tracking_number` → 422.
- `scripts/seed_inventory.py`: 6 SKUs, 7 recepciones, 4 salidas; verifica el
   stock neto (LA: CLT-SNK-W-42 165, TEC-EAR-001 58, CLT-CHN-N-32 45; ZGZ:
   CLT-SNK-W-42-Z 87, CSM-SRM-030 126, TEC-CHG-065 40).
- Verificado: `uv run pytest` en verde (20 tests nuevos en
   `tests/inventory`), prueba HTTP completa con `uvicorn` y seed contra SQLite.
- Supabase: la API crea el esquema al arrancar; el seed insertó
   6 SKUs y 11 movimientos, y la segunda ejecución no duplicó nada.
   `GET /inventory/products` devuelve el stock neto esperado,
   `GET /inventory/orders` 11 órdenes con SKU y `user_uuid`, y una salida de
   41 sobre 40 da 400 sin escribir (siguen 11 órdenes). Sin token → 401.
- La contraseña de `DATABASE_URL` va sin los corchetes del ejemplo de Supabase.
- El 400 de stock insuficiente va en inglés a propósito: es el texto literal
   que TrackFlow fija para la API.
- Siguiente paso: demo del hito.

### Milestone 09 — Batería de pruebas (AUTH-088, API-042, FE-019)

- pytest en `tests/`: `tests/auth` (un módulo por endpoint, feliz/límite/fallo),
   `tests/backoffice` (proveedores e incidencias) y `tests/http` (integración
   movida desde `services/api/`). Plan, ejecución y cobertura en `TESTING.md`.
- Jest en `uis/backoffice/__tests__`: `api-client`, `registration`, `incidents`
   y `labels`.
- Bugs corregidos: contraseñas de más de 72 bytes daban 500 (ahora 422 en el
   alta y 401 en el login); el registro del backoffice contaba caracteres en vez
   de bytes; `formatIncidentDate` lanzaba con fechas inválidas.
- Verificado: `uv run pytest` 146 en verde; cobertura de auth 97–100 % y de
   backoffice 91–100 % con solo sus tests unitarios; `npm test` 40 en verde;
   typecheck y lint del backoffice sin errores.
- Siguiente paso: incluir `uv run pytest` y `npm test` en `npm run verify`.

### Milestone 09 — Auditoría de gestión de errores

- Backend: el 422 ya no devuelve `input` (contraseñas y tokens) y sus mensajes
   están en español (`services/api/errors.py`, compartido con incidencias).
   Sin `JWT_SECRET_KEY` responde 500 genérico en vez de 401. Resend se aísla
   en `EmailDeliveryError`, cuyo mensaje no incluye el destinatario ni el enlace.
- Scripts: `analyze.py`, `seed_incidents.py`, `services/api/seed.py` y
   `pandas_clean.py` comprueban la entrada antes de procesar, acotan
   `try/except` a CSV, BD o exportación, escriben en `stderr` y salen con 1.
- Frontend: `api-client` (backoffice) y `recordsApi` (tracker) nunca muestran
   el cuerpo crudo, `Failed to fetch` ni errores de parseo. Proveedores,
   análisis CSV y tracker tienen carga, error con «Reintentar» y `finally`.
   Un fallo de red al restaurar la sesión ya no cierra la sesión en silencio.
   Las tres apps tienen `error.tsx`, `global-error.tsx` y `not-found.tsx`.
- Verificado: 33 pruebas Python (5 nuevas), `npm run verify` con código 0,
   build del tracker y rutas 200/404 en las tres apps con `npm run dev`.
- Siguiente paso: revisión visual de los estados de error en el navegador.

### Milestone 09 — Gestor de incidencias centralizado

- Validación del CSV extraída a `packages/shared/incidents/` (Python) y
   reutilizada por el analizador, la API y el seed; el analizador sigue dando
   100 / 95 válidos / 5 inválidos.
- API `/api/incidents` (TinyDB `incidents.json`): alta, listado con filtros,
   detalle, cambio de estado con ciclo de vida y `/summary`. Validación `400`
   con campo afectado y `500` genérico sin traza.
- `scripts/seed_incidents.py`: 95 insertadas y 5 descartadas (reportadas por
   línea) en la primera ejecución, 0 en la segunda. Summary tras el seed:
   open 29 / resolved 52 / discarded 14; lost_parcel 14 / carrier_issue 45 /
   delivery_failure 19 / returns_issue 17, igual que el CONTEXT.
- Backoffice: `/incidents` (resumen + listado con filtros y cambio de estado
   optimista con reversión), `/incidents/new` (formulario táctil, sede
   destacada si el origen es `branch`). El analizador CSV pasa a
   `/incidents/analyzer`.
- Verificado: 28 pruebas Python (11 nuevas), `npm run verify` con código 0
   (tras `npm ci` en la raíz) y HTTP por rewrites (201/400/404/401 y 500 con la
   API caída). Rutas `/`, `/incidents`, `/incidents/new`, `/incidents/analyzer`
   y `/suppliers` → 200 sin valores crudos en el HTML.
- Los `__pycache__/*.pyc` dejan de versionarse (`.gitignore`).
- Siguiente paso: revisión visual en navegador del formulario y del listado
   y ejecutar `uv run python scripts/seed_incidents.py` en cada entorno.

### Milestone 09 — AUTH-03 Recuperación de contraseña

- API de recuperación con token firmado de 30 minutos y hash persistido en TinyDB;
   consumo único y cambio autenticado de contraseña.
- Resend envía enlaces configurados por entorno; el remitente de onboarding solo
   admite el email de la cuenta hasta verificar un dominio.
- Backoffice añade recuperación y restablecimiento públicos, y cambio desde el perfil.
- Pruebas HTTP automatizadas cubren firma, expiración, reutilización y cambio;
   el envío real sigue pendiente: Resend rechazó el destinatario de prueba con
   `validation_error` (el remitente onboarding solo permite el email de la cuenta).
   Siguiente paso: usar esa dirección registrada o verificar un dominio y cambiar
   el remitente. El SDK oficial sustituye al cliente HTTP que recibió el bloqueo
   Cloudflare 1010 previo al servicio.
- El cliente HTTP se sustituyó por el SDK oficial de Resend y se confirmó un
   envío de diagnóstico aceptado por el proveedor al destinatario autorizado.
   La dirección autorizada ya está registrada y activa: `/auth/forgot-password`
   respondió 200, el SDK no notificó error y el token quedó persistido. Falta
   confirmar la recepción en el buzón y completar el formulario con el enlace.
- Un enlace emitido con `localhost:3002` devolvió 404 fuera del contenedor. En
   Codespaces se genera ahora la URL HTTPS del puerto reenviado; se envió un
   enlace nuevo para invalidar el token expuesto y se permitió abrir reset con
   sesión activa. El usuario completó el formulario: la API registró
   `POST /auth/reset-password` con 200 y el token pendiente desapareció. El
   usuario confirmó el acceso posterior y la API registró `POST /auth/login` y
   `GET /auth/me` con 200: flujo completo verificado sin compartir contraseñas.

### Milestone 09 — Flujos de autenticación frontend

- Añadidas las vistas `/login`, `/register` y `/account/profile` al backoffice.
- El JWT se guarda en `localStorage`; `apiFetch` lo adjunta a proveedores,
   incidencias, perfil y autenticación, y expulsa la sesión ante cualquier `401`.
- `AuthProvider` concentra usuario, carga, login, registro automático y logout;
   `ProtectedShell` protege las vistas internas exclusivamente en cliente.
- El website público permanece sin cambios y sin comprobaciones de sesión.
- Verificado: typecheck, lint, build y flujo HTTP por rewrites (`201`, `200`,
   actualización de perfil y `401` con bearer inválido).

### Milestone 09 — Autenticación y restricción de rutas

- Implementados usuarios y perfiles uno a uno exclusivamente en TinyDB, con
   UUID, roles validados y contraseñas bcrypt.
- Añadidos login JWT, `get_current_user`, CRUD protegido de usuarios y perfil
   propio; el acceso cruzado responde `403`.
- Protegidas las seis operaciones de proveedores y las dos rutas de incidencias.
- Verificado con nueve pruebas HTTP: registro, login JSON/OAuth2, perfil,
   permisos, cascada, token ausente, mal formado y expirado.

### Milestone 09 — Directorio de proveedores

- Implementada la API FastAPI con modelos Pydantic, TinyDB persistente, CRUD, filtros por país/categoría y actualizaciones de tarifa con `updated_at`.
- El seeder carga los 15 proveedores del contexto y es idempotente mediante `uv run seed`.
- El backoffice añade `/suppliers` con filtros, alta, edición de tarifa y activación/suspensión visual.
- Verificado: `uv run seed` (15 y 0), contratos HTTP (422/404/timestamp), Uvicorn (200/404) y typecheck/lint del backoffice.

## Estado actual

### ✅ Lo que funciona

- **Lógica de negocio (`src/`)** — las 19 funciones del Hito 2 y sus modelos. `npm run check:ts` pasa.
- **Web pública (`uis/website`)** — la web del Hito 1 en Next.js 16 con componentes tipados. La ruta `/` tiene hero, servicios,
  beneficios, contacto, footer y JSON-LD `Organization`; la ruta `/aplicar`, el formulario B2B con las mismas reglas que el antiguo `uis/website/validation.js` del Hito 1 (eliminado en el Hito 4).
- **Backoffice (`uis/backoffice`)** — layout propio (sidebar y barra superior) y panel de operaciones en `/` que muestra la salida del
  Hito 2: KPIs, inventario por stock, distribución, simulador de transportista, ranking de fiabilidad, envíos por estado, buscador (ID, SKU
  y búsqueda binaria por peso) e informe de validaciones.
- **Infraestructura de agentes** — `memory-bank/`, `AGENTS.md`, 3 reglas en `.agents/rules/` y 1 skill en `.agents/skills/`.
- **Verificación** — `npm run verify` pasa (tipos, lint y build de ambas apps).

---

### ⚠️ Problemas conocidos

**1. `selectBestCarrier` puede recomendar un transportista que no puede entregar.** Según la especificación del Hito 2, un transportista con
50 puntos o más es "apto" y gana el más barato. Para el envío de ejemplo `SH-2024-8821` (Zaragoza → Madrid) el resultado es **UPS** (76,4
puntos, 30,89 USD), aunque UPS solo opera en EE. UU. El backoffice muestra la recomendación tal cual y añade un aviso de "Revisión manual"
(`findHardConstraintIssues` en `uis/backoffice/lib/carrier-evaluation.ts`).

**Propuesta:** confirmar con Carlos Vega y Ana Whitfield si país, peso, prioridad y fragilidad deben ser filtros eliminatorios y, si es así,
cambiar `src/utils/transformations.ts` en una tarea propia.

**2. El formulario `/aplicar` no envía datos.** Igual que en el Hito 1, muestra el mensaje de éxito solo en el cliente. Necesita un
endpoint en `services/` (Hito 5).

---

### 🔜 Próximos pasos

1. **Hito 5 — Backend:** crear `services/core-api` (inventario, envíos y transportistas) reutilizando los tipos de `src/types/models.ts`,
   sustituir `uis/backoffice/lib/sample-data.ts` por llamadas a esa API y recibir el formulario de `/aplicar`.
2. **Tests:** añadir tests unitarios de `src/utils/*` (valores de control de `.agents/rules/business-logic.md` y casos límite) e incluirlos en
   `npm run verify`.
3. **Backoffice:** convertir las secciones del panel en rutas propias (`/inventario`, `/transportistas`, `/envios`) cuando tengan datos
   reales. Los módulos marcados "Próximo" en el sidebar (Devoluciones, CX, Dashboard ejecutivo) esperan a sus hitos.
4. **Tipos compartidos:** valorar mover `src/types` a `packages/shared` cuando haya un segundo consumidor (la API).

---

## Historial

### Inventario con ORM y doble base de datos

API de inventario unificada por SKU y almacén: el stock solo cambia con
recepciones y salidas trazables al usuario que las registra.

### Batería de pruebas

Pruebas unitarias de la lógica de autenticación, backoffice y utilidades del
frontend tras la regresión de caducidad de tokens; tres bugs corregidos.

### Auditoría de gestión de errores

Estrategia común de errores en frontend, backend y scripts: mensajes legibles
con salida clara, sin datos sensibles en respuestas y códigos de salida
correctos en los scripts.

### Gestor de incidencias centralizado

Registro, seguimiento y métricas de incidencias persistidas, con el histórico
CSV cargado como incidencias de cliente. La validación del analizador vive
ahora en `packages/shared/incidents/` y no se duplica.

### AUTH-03

Recuperación por correo y cambio autenticado de contraseña con consumo único del
token. Pendiente de confirmar el envío real con `RESEND_API_KEY` configurada.

### AUTH-02

El backoffice cierra el ciclo JWT con registro, login, guard cliente, cliente API
autenticado, cierre global por `401` y edición del perfil. El website público no
se modifica.

### AUTH-01

La API incorpora autenticación JWT stateless bajo `/auth`, CRUD de credenciales
bajo `/users` y perfiles bajo `/profiles`. La persistencia de identidad queda
aislada en TinyDB y las rutas operativas existentes requieren bearer token.

### Analizador interno de incidencias

Se incorpora el CLI en `scripts/incidents-analyzer/`, un analizador Python
compartido con `services/api` y la ruta `/incidents` del backoffice. La muestra
de TrackFlow confirma 100 registros, 95 válidos, 5 inválidos y satisfacción
media de 3.06; la API solo devuelve y exporta métricas agregadas. `npm run verify`,
las pruebas unitarias del analizador y las comprobaciones HTTP locales pasan.

---

### 🤖 — Nueva versión de `AGENTS.md`

El desarrollador sustituyó `AGENTS.md` por una guía propia con pasos antes de la entrega. La guía se actualizó para que el alcance vigente
sea el Milestone 09 y para retirar restricciones heredadas de hitos anteriores.

---

### 🗂️ — Documentación alineada con `uis/`

Los README de la raíz ya describen el estado real: `src/`, `uis/` (website :3000, backoffice :3002, tracker), `services/`, `AGENTS.md`,
`memory-bank/`, `.agents/` y los scripts de la raíz. Los README de la plantilla en `packages/`, `shared/` y `workflows/` hablaban de `apps/`,
que en este monorepo es `uis/`. Las menciones a `validation.js` indican ahora que era un archivo del Hito 1 ya eliminado. Todas las rutas
citadas en la documentación existen, salvo `services/core-api` (prevista para el Hito 5).

---

### 🔧 — `src/` expone el umbral y los criterios del scoring

Con autorización del desarrollador, `src/utils/transformations.ts` exporta `CARRIER_SUITABILITY_THRESHOLD` (50) y
`checkCarrierConstraints` (país, peso, prioridad y fragilidad), que ahora usan internamente `scoreCarrierForShipment` y `selectBestCarrier`.
El backoffice los importa en lugar de repetir esa lógica en `uis/`, para no duplicar lógica de negocio. El
comportamiento no cambia: 648 combinaciones de producto, transportista, prioridad, país y cantidad dan el mismo resultado que antes, y los
valores de control siguen en 46,22 USD / 97,6.

---

### 📝 — Documentación con el formato de CONTEXT.md

Los `.md` del Hito 4 (banco de memoria, `AGENTS.md`, reglas, skill y README de `uis/website` y `uis/backoffice`) siguen ahora la estructura
de `CONTEXT.md`.

---

### 🧠 Hito 4

Web del Hito 1 migrada a `uis/website` (Next.js); los HTML y JS estáticos se eliminan (siguen en git, commit `33fc434`). Nuevo
`uis/backoffice`, integrado con `src/` mediante un alias y `turbopack.root`. Se crean el banco de memoria, `AGENTS.md`, las reglas y la skill
`delivery-checklist`. Se añade un `.gitignore` en la raíz y se deja de versionar el `node_modules/` de la raíz. El backoffice usa el puerto 3002
para no chocar con la API por defecto del tracker (3001).

---

### 👥 Hito 3

`uis/talent-pipeline-tracker` (PR #2).

---

### 🧮 Hito 2

Lógica de negocio en `src/` (PR #1).

---

_Documento interno — 4Geeks Academy · AI Engineering Track_
_Banco de memoria de TrackFlow Tech · Añade una entrada en cada cambio relevante_
