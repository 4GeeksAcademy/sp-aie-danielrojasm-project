# Tech context del monorepo TrackFlow

## AI Engineering · 4Geeks Academy — Banco de memoria: contexto técnico

---

Este archivo describe cómo está construido el monorepo: qué hay en cada carpeta, con qué stack, qué decisiones de arquitectura se han
tomado y qué restricciones técnicas están en vigor. Hay que actualizarlo cada vez que cambie cualquiera de ellas.

El monorepo parte de la plantilla del programa de 4Geeks Academy. Hoy contiene la lógica de negocio del Hito 2 en `src/`, tres interfaces
en `uis/` y la configuración de agentes de código del Hito 4. Todavía no hay ningún servicio de backend propio.

## Mapa del monorepo

- **`src/`** — lógica de negocio del Hito 2 en TypeScript puro y sin dependencias (`types/models.ts` y
  `utils/{collections,search,transformations,validations}.ts`). Es la fuente única: se importa, no se copia.
- **`uis/website/`** — web pública (Hito 1 migrado a Next.js), con las rutas `/` y `/aplicar`.
- **`uis/backoffice/`** — app interna de la empresa. Su ruta `/` es el panel de operaciones que consume `src/`.
- **`uis/talent-pipeline-tracker/`** — Hito 3, gestor de candidaturas contra una API REST externa. No se toca sin pedirlo.
- **`services/`** — APIs y workers. Está vacío: **toda API nueva va aquí**.
- **`packages/shared/`** — paquete `@repo/shared-types` de la plantilla, todavía sin uso.
- **`memory-bank/`, `AGENTS.md`, `.agents/`** — configuración de los agentes de código (Hito 4).
- **`agents/`, `skills/`, `mcps/`, `workflows/`, `data/`, `infra/`** — espacio para el producto de hitos futuros (agentes de la empresa,
  no del IDE). Solo contienen la plantilla.

---

## Stack

### ⚙️ Runtime y lógica de negocio

**Node.js:** 24.x LTS (instalado con winget en la máquina de desarrollo)

**TypeScript en la raíz:** `typescript ^6.0.3`. El `tsconfig.json` raíz es `strict`, usa `moduleResolution: Bundler` y solo incluye
`src/**/*.ts`.

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

### 🚫 Sin APIs dentro de `uis/`

Nada de `app/api/*` ni route handlers en las interfaces. Cuando haga falta backend, se crea en `services/<nombre>`. Mientras tanto, el
backoffice usa datos de ejemplo en `uis/backoffice/lib/sample-data.ts` (el dataset de referencia del Hito 2 más FedEx y envíos extra), que se
sustituirán por la API de `services/` en el Hito 5.

---

## Puertos de desarrollo

- **`uis/website`** — puerto **3000**, con `npm run dev` o `npm run dev:website` desde la raíz.
- **`uis/backoffice`** — puerto **3002**, con `npm run dev` o `npm run dev:backoffice` desde la raíz.
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

---

## Restricciones técnicas

- **Sin tests automatizados** — todavía no hay; `npm run verify` (tipos, lint y build) es la red de seguridad.
- **`src/` aislado** — no puede importar nada de `uis/` ni paquetes npm; debe compilar con el `tsconfig.json` raíz.
- **Imágenes remotas** — solo desde `images.unsplash.com` (`images.remotePatterns`). Next 16 solo permite `quality` 75 por defecto.
- **Windows** — tras instalar Node, `npm` y `node` pueden no estar en el PATH de las terminales ya abiertas: hay que reiniciarlas.
- **`node_modules/`** — la carpeta de la raíz estuvo versionada por error; desde el Hito 4 la ignora `.gitignore`.

---

_Documento interno — 4Geeks Academy · AI Engineering Track_
_Banco de memoria de TrackFlow Tech · Actualízalo cuando cambie el stack, una decisión, un puerto o un comando_
