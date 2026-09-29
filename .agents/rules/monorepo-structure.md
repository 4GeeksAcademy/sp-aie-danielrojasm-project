---
description: Estructura del monorepo TrackFlow, dónde vive cada tipo de código y cómo se reutiliza la lógica compartida.
trigger: always_on
globs: "**/*"
---

# Regla: estructura del monorepo

## AI Engineering · 4Geeks Academy — Regla de agente de código

---

**Alcance:** siempre activa (`trigger: always_on`). Aplica a cualquier archivo que el agente cree, mueva o borre.

El monorepo de TrackFlow Tech va a crecer con APIs, agentes y automatizaciones en los próximos hitos. Esta regla evita que cada pieza acabe en
un sitio distinto: fija dónde vive cada tipo de código y cómo se reutiliza la lógica compartida sin duplicarla.

## Lo obligatorio

### 🖥️ Una interfaz, una carpeta en `uis/`

Cada interfaz tiene su carpeta (`uis/website`, `uis/backoffice`, `uis/talent-pipeline-tracker`) y es un proyecto npm independiente con su
`package.json`, `package-lock.json`, `README.md` y `AGENTS.md`. No se crean apps fuera de `uis/`.

---

### 🔌 APIs y workers solo en `services/`

Toda API o worker va en `services/<nombre>/`. Están prohibidos `app/api/**`, `route.ts` y las Server Actions que hagan de backend dentro de
`uis/`. Si una interfaz necesita datos que todavía no existen, usa datos de ejemplo tipados en `uis/<app>/lib/` y lo anota en
`memory-bank/progress.md`, dentro de "Próximos pasos".

---

### 🔗 La lógica compartida se importa, nunca se copia

La lógica de negocio vive en `src/`. En el backoffice se importa así:

- **Funciones:** `import { selectBestCarrier } from "@trackflow/logic/utils/transformations";`
- **Tipos:** `import type { Product } from "@trackflow/logic/types/models";`

Está prohibido pegar el cuerpo de una función de `src/utils/*` dentro de `uis/**`. Si hace falta otra forma de salida, se escribe un
adaptador en `uis/<app>/lib/` que **llame** a la función original, como `uis/backoffice/lib/carrier-evaluation.ts`.

Para usar `src/` desde una app nueva se replica la configuración del backoffice: el alias `@trackflow/logic/*` en `tsconfig.json` y
`turbopack.root` más `outputFileTracingRoot` apuntando a la raíz del monorepo en `next.config.ts`.

---

### 🧱 `src/` no depende de nada

`src/` no importa nada de `uis/`, ni React, ni paquetes npm. Tiene que pasar `npm run check:ts`.

---

### 🗂️ Antes de crear una carpeta en la raíz

Hay que leer el `README.md` de las carpetas existentes (`packages/`, `shared/`, `docs/`, `services/`…) y usar la que corresponda. Si ninguna
encaja, se pregunta.

---

### 🤖 `.agents/` no es `agents/` ni `skills/`

Las reglas y skills del agente de código van en `.agents/`. Los agentes de IA de la empresa (producto) van en `agents/`, y las skills de
producto en `skills/`.

---

## Cómo comprobarla

- **Sin APIs en `uis/`:** `git ls-files uis | grep -E "app/api/|route\.ts$"` no devuelve nada.
- **Sin lógica copiada:** `git grep -n "export function selectBestCarrier" -- uis` no devuelve nada, porque la función solo existe en `src/`.

---

_Documento interno — 4Geeks Academy · AI Engineering Track_
_Regla siempre activa para agentes de código en el monorepo de TrackFlow_
