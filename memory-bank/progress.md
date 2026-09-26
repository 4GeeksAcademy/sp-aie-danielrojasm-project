# Progreso de TrackFlow Tech

## AI Engineering · 4Geeks Academy — Banco de memoria: estado del desarrollo

---

Este es el registro vivo del proyecto: qué funciona, qué problemas conocemos y qué viene después. Cada cambio relevante (una feature, una
decisión o un problema nuevo) añade una entrada al principio del **Historial**. No es un roadmap de marketing.

**Rama actual:** `hito4` (sigue a `origin/hito-4`)

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

### Analizador interno de incidencias

Se incorpora el CLI en `scripts/incidents-analyzer/`, un analizador Python
compartido con `services/api` y la ruta `/incidents` del backoffice. La muestra
de TrackFlow confirma 100 registros, 95 válidos, 5 inválidos y satisfacción
media de 3.06; la API solo devuelve y exporta métricas agregadas. `npm run verify`,
las pruebas unitarias del analizador y las comprobaciones HTTP locales pasan.

---

### 🤖 — Nueva versión de `AGENTS.md`

El desarrollador sustituye `AGENTS.md` por una guía propia con 6 pasos antes del commit, y después se reescribe con otras palabras sin
cambiar su significado. Se ajusta para que encaje con el repo: la lectura inicial incluye las reglas de `.agents/rules/` y la skill
`delivery-checklist`; el paso 2 usa `npm run verify` y `npm run dev`; las rutas protegidas dejan fuera dos archivos que no existían
y añaden `src/**` y `uis/talent-pipeline-tracker/**`. La skill habla ahora de
"rutas protegidas (sección 4)", como `AGENTS.md`.

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
