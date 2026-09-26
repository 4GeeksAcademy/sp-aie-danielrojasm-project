# Tech context — TrackFlow monorepo

> Contexto técnico: stack, decisiones de arquitectura tomadas y restricciones. Actualízalo cuando cambie cualquiera de ellas.

## Mapa del monorepo (lo que existe hoy)

| Ruta | Qué es | Estado |
| --- | --- | --- |
| `src/` | **Lógica de negocio del Hito 2** (TypeScript puro, sin dependencias). `types/models.ts` + `utils/{collections,search,transformations,validations}.ts` | Estable. Fuente única; se importa, no se copia |
| `uis/website/` | Web pública (Hito 1 migrado a Next.js). Rutas `/` y `/aplicar` | Activo |
| `uis/backoffice/` | App interna de la empresa. Ruta `/` = panel de operaciones que consume `src/` | Activo |
| `uis/talent-pipeline-tracker/` | Hito 3: gestor de candidaturas contra API REST externa | Entregado, no tocar sin pedirlo |
| `services/` | APIs y workers | Vacío. **Toda API nueva va aquí** |
| `packages/shared/` | `@repo/shared-types` (plantilla, sin uso aún) | Placeholder |
| `memory-bank/`, `AGENTS.md`, `.agents/` | Configuración de agentes de código | Hito 4 |
| `agents/`, `skills/`, `mcps/`, `workflows/`, `data/`, `infra/` | Código de producto de hitos futuros (agentes de la empresa, NO del IDE) | Plantilla |

## Stack

| Capa | Tecnología | Versión fijada |
| --- | --- | --- |
| Runtime | Node.js LTS | 24.x (instalado con winget en la máquina de desarrollo) |
| Lógica de negocio | TypeScript (raíz) | `typescript ^6.0.3`, `tsconfig.json` raíz: `strict`, `moduleResolution: Bundler`, solo `src/**/*.ts` |
| Frontends | Next.js (App Router, Turbopack) + React | `next 16.2.10`, `react 19.2.4` (mismas versiones en las tres apps) |
| Estilos | Tailwind CSS v4 vía `@tailwindcss/postcss` | `^4` — sin `tailwind.config.js`; tokens en `app/globals.css` con `@theme` |
| Lint | ESLint 9 flat config + `eslint-config-next` | `16.2.10` |
| Tipos en apps | TypeScript 5 | `^5` |

> Next 16 tiene cambios incompatibles con versiones anteriores. Antes de usar una API de Next, lee la guía en
> `uis/<app>/node_modules/next/dist/docs/` (lo exige el `AGENTS.md` de cada app).

## Decisiones de arquitectura (ADR resumidos)

1. **Apps independientes, sin npm workspaces.** Cada app de `uis/` tiene su `package.json` y `package-lock.json`. Motivo: el Hito 3
   ya funcionaba así y la plantilla no define runner de workspaces. Consecuencia: `npm install` se ejecuta dentro de cada app
   (o `npm run install:uis` desde la raíz).
2. **La lógica del Hito 2 se importa desde `src/`, nunca se copia.** El backoffice la resuelve con el alias
   `@trackflow/logic/*` → `../../src/*` (`uis/backoffice/tsconfig.json`) y amplía `turbopack.root` y `outputFileTracingRoot` a la
   raíz del monorepo (`uis/backoffice/next.config.ts`), porque Turbopack no resuelve archivos fuera de su raíz.
3. **`uis/website` fija `turbopack.root` a su propia carpeta** para que Next no tome el `package-lock.json` de la raíz como raíz
   del proyecto (aviso de "multiple lockfiles").
4. **Contenido de la web separado de la presentación.** Textos, enlaces y datos de empresa en `uis/website/content/site.ts`,
   tipados en `uis/website/types/site.ts`; componentes en `components/{layout,sections,ui,forms,seo}`.
5. **Validación de formularios como funciones puras** (`uis/website/lib/application-form.ts`), portadas de `validation.js`
   del Hito 1. El componente cliente solo gestiona estado.
6. **Layouts separados.** Web pública: cabecera + footer oscuros (marca slate-950/cyan-300). Backoffice: sidebar + barra
   superior, fondo claro y `robots: noindex`. No comparten layout ni componentes.
7. **Etiquetas de dominio centralizadas** en `uis/backoffice/lib/labels.ts` (`Record<Tipo, string>`), para que un valor nuevo del
   modelo rompa el tipado en vez de mostrarse crudo.
8. **Sin APIs dentro de `uis/`** (ni `app/api/*`, ni route handlers). Cuando haga falta backend, se crea en `services/<nombre>`.
9. **Datos de ejemplo** del backoffice en `uis/backoffice/lib/sample-data.ts` (dataset de CONTEXT2 + FedEx y envíos extra).
   Se sustituirán por la API de `services/` en el Hito 5.

## Puertos de desarrollo

| App | Comando | Puerto |
| --- | --- | --- |
| `uis/website` | `npm run dev` (o `npm run dev:website` en la raíz) | 3000 |
| `uis/backoffice` | `npm run dev` (o `npm run dev:backoffice`) | 3002 |
| `uis/talent-pipeline-tracker` | `npm run dev -- --port 3003` | 3000 por defecto → choca con website |

El backoffice **no** usa el 3001 porque el tracker del Hito 3 usa `http://localhost:3001` como API por defecto si no hay
`NEXT_PUBLIC_TRACKFLOW_API_BASE_URL`.

## Comandos de verificación

| Comando (desde la raíz) | Qué comprueba |
| --- | --- |
| `npm run check:ts` | Tipos de `src/` (Hito 2) |
| `npm run typecheck:uis` | `tsc --noEmit` en website y backoffice |
| `npm run lint:uis` | ESLint en website y backoffice |
| `npm run build:uis` | `next build` de ambas apps (detecta imports rotos hacia `src/`) |
| `npm run verify` | Todo lo anterior en orden. Es la puerta obligatoria antes de commit |

## Restricciones técnicas

- No hay tests automatizados todavía: `verify` (tipos + lint + build) es la red de seguridad. Añadir tests es un paso siguiente.
- `src/` no puede importar nada de `uis/` ni dependencias npm: debe seguir compilando con el `tsconfig.json` raíz.
- Las imágenes remotas de la web solo pueden venir de `images.unsplash.com` (`images.remotePatterns`). Next 16 solo permite
  `quality` 75 por defecto.
- En Windows, `npm`/`node` pueden no estar en el PATH de shells ya abiertos tras instalar Node: reinicia la terminal.
- Históricamente `node_modules/` de la raíz estaba versionado por error; desde el Hito 4 lo ignora `.gitignore`.
