---
description: Estructura del monorepo TrackFlow, dónde vive cada tipo de código y cómo se reutiliza la lógica del Hito 2.
trigger: always_on
globs: "**/*"
---

# Regla: estructura del monorepo

**Alcance: siempre activa** (`trigger: always_on`). Aplica a cualquier archivo que el agente cree, mueva o borre.

## Obligatorio

1. **Una interfaz = una carpeta en `uis/`** (`uis/website`, `uis/backoffice`, `uis/talent-pipeline-tracker`). Cada app es un
   proyecto npm independiente con su `package.json`, `package-lock.json`, `README.md` y `AGENTS.md`. No crees apps fuera de `uis/`.
2. **APIs y workers solo en `services/<nombre>/`.** Prohibido crear `app/api/**`, `route.ts` o Server Actions que actúen como
   backend dentro de `uis/`. Si una UI necesita datos que no existen, usa datos de ejemplo tipados en `uis/<app>/lib/` y anótalo en
   `memory-bank/progress.md` → "Próximos pasos".
3. **La lógica de negocio del Hito 2 vive en `src/` y se importa, nunca se copia.**
   - En el backoffice: `import { selectBestCarrier } from "@trackflow/logic/utils/transformations";`
   - Tipos: `import type { Product } from "@trackflow/logic/types/models";`
   - Prohibido pegar el cuerpo de una función de `src/utils/*` en `uis/**`. Si necesitas otra forma de salida, escribe un
     adaptador en `uis/<app>/lib/` que **llame** a la función original (ejemplo: `uis/backoffice/lib/carrier-evaluation.ts`).
   - Para usar `src/` desde otra app nueva, replica la configuración del backoffice: alias `@trackflow/logic/*` en `tsconfig.json`
     + `turbopack.root` y `outputFileTracingRoot` apuntando a la raíz del monorepo en `next.config.ts`.
4. **`src/` no depende de nada**: sin imports de `uis/`, de React ni de paquetes npm. Debe pasar `npm run check:ts`.
5. **Antes de crear una carpeta de primer nivel**, lee el `README.md` de las existentes (`packages/`, `shared/`, `docs/`, `services/`…)
   y usa la que corresponda. Si ninguna encaja, pregunta.
6. **`.agents/` ≠ `agents/` ≠ `skills/`.** Reglas/skills del agente de código → `.agents/`. Agentes de IA de la empresa (producto)
   → `agents/`. Skills de producto → `skills/`.

## Comprobación rápida

- `git ls-files uis | grep -E "app/api/|route\.ts$"` → no debe devolver nada.
- `git grep -n "export function selectBestCarrier" -- uis` → no debe devolver nada (la función solo existe en `src/`).
