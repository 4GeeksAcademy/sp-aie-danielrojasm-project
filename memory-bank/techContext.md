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
