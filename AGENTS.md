# AGENTS.md — cómo opera un agente de código en este monorepo

Este repositorio es el núcleo técnico de **TrackFlow Tech** (logística de última milla, Los Ángeles + Zaragoza).
Aplica a cualquier agente de programación (Claude Code, Cursor, Windsurf, Copilot…). Las reglas específicas están en
[`.agents/rules/`](.agents/rules/) y las tareas reutilizables en [`.agents/skills/`](.agents/skills/).

> No confundir `.agents/` (configuración del agente de código) con `agents/` y `skills/` (producto: agentes que TrackFlow
> construirá en hitos futuros).

## 1. Al empezar cada sesión (obligatorio, antes de editar nada)

Lee, en este orden:

1. [`memory-bank/projectbrief.md`](memory-bank/projectbrief.md) — negocio, personas, KPIs y restricciones de negocio.
2. [`memory-bank/techContext.md`](memory-bank/techContext.md) — mapa del repo, stack, decisiones de arquitectura, puertos y comandos.
3. [`memory-bank/progress.md`](memory-bank/progress.md) — qué funciona, problemas conocidos y próximos pasos.
4. Las reglas de [`.agents/rules/`](.agents/rules/) cuyo alcance cubra los archivos que vas a tocar (la de alcance `always` siempre).

Si la tarea toca una app Next.js, lee además el `AGENTS.md` de esa app (`uis/<app>/AGENTS.md`) y la guía correspondiente en
`uis/<app>/node_modules/next/dist/docs/`.

Si algo del banco de memoria contradice el código o `CONTEXT*.md`, **para y avisa** antes de continuar; no elijas tú la versión buena.

## 2. Flujo obligatorio antes de cada commit

Ejecuta estos pasos **en orden**. Si uno falla, corrige y vuelve a empezar desde el paso 1. El procedimiento detallado y
verificable es la skill [`delivery-checklist`](.agents/skills/delivery-checklist/SKILL.md).

1. **Revisar el alcance del diff**: `git status` y `git diff --stat`. Cada archivo cambiado debe pertenecer a la tarea pedida; revierte
   lo que no. Ningún archivo de la lista de "Zonas protegidas" puede aparecer sin confirmación explícita.
2. **Verificar**: `npm run verify` desde la raíz (tipos de `src/`, `tsc` + ESLint + `next build` de `uis/website` y `uis/backoffice`).
   Debe terminar con código 0. Si cambiaste `uis/talent-pipeline-tracker`, ejecuta además `npm run lint` y `npm run build` dentro.
3. **Probar en ejecución** lo que cambió: arranca la app afectada con `npm run dev` y comprueba que la ruta tocada responde
   200 sin errores en la consola del servidor.
4. **Actualizar el banco de memoria**: añade una entrada en `memory-bank/progress.md` (historial + estado) y, si cambió el stack,
   una decisión, un puerto o un comando, actualiza `memory-bank/techContext.md`.
5. **Commit** en una rama distinta de `main` (este hito: `hito4`), con mensaje en español en imperativo que diga qué y por qué.
   Nunca `--no-verify`, nunca `push --force` sin permiso.

**Nunca** hagas commit directamente en `main`. El trabajo llega a `main` solo por Pull Request.

## 3. Zonas protegidas (no modificar sin confirmación explícita del desarrollador)

| Ruta | Motivo |
| --- | --- |
| `CONTEXT.md`, `CONTEXT2.md`, `Context3.md` | Enunciados de la empresa y de los hitos: son fuente de verdad, no documentación editable |
| `src/**` | Lógica del Hito 2 ya entregada y evaluada contra su spec. Se **importa**; cambiar su comportamiento es una tarea propia |
| `uis/talent-pipeline-tracker/**` | Hito 3 entregado |
| `**/package-lock.json` | Solo cambian como efecto de un `npm install` pedido; nunca a mano |
| `**/next.config.ts`, `**/tsconfig.json`, `**/eslint.config.mjs` | Contienen el alias `@trackflow/logic` y `turbopack.root`; un cambio rompe la integración con `src/` |
| `.env*` (salvo `.env.example`) | Secretos y URLs locales |
| `.git/`, `.github/` (si existe), historial de ramas | Nada de reescribir historial ni borrar ramas |
| `README.md` / `README.es.md` de las carpetas de plantilla | Instrucciones del programa; se amplían, no se sustituyen |

Además, **para y pregunta** antes de: instalar o actualizar dependencias, borrar archivos que no creaste en esta sesión, crear una
carpeta de primer nivel nueva, o hacer push / abrir PR.

## 4. Dónde va cada cosa

- Interfaz nueva → `uis/<nombre-app>/` (una carpeta por interfaz, con su README).
- API o worker → `services/<nombre-servicio>/`. **Nunca** route handlers (`app/api/*`) en `uis/`.
- Lógica de negocio reutilizable → `src/` (con confirmación, ver zonas protegidas) o, si la usan varias apps, `packages/`.
- Documentación transversal → `docs/`. Contexto del agente → `memory-bank/`.
