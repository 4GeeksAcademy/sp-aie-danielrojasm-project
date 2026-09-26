# Progress — estado del desarrollo

> Registro vivo. Añade una entrada al principio de "Historial" en cada cambio relevante (feature, decisión, problema).
> No lo conviertas en un roadmap de marketing: qué funciona, qué no y qué sigue.

## Estado actual (Hito 4 — rama `hito4` → `origin/hito-4`)

### Funciona

- [x] `src/` — lógica de negocio del Hito 2 (19 funciones + modelos). `npm run check:ts` pasa.
- [x] `uis/website` — web corporativa del Hito 1 en Next.js 16 con componentes tipados:
  - `/`: hero, servicios, beneficios, contacto, footer y JSON-LD `Organization` (contenido completo del Hito 1).
  - `/aplicar`: formulario de aplicación B2B con las mismas reglas de validación que `validation.js`.
- [x] `uis/backoffice` — layout propio (sidebar + barra superior) y panel de operaciones en `/` que muestra en pantalla la salida
  de las funciones del Hito 2: KPIs, inventario por stock, distribución, simulador de transportista, ranking de fiabilidad,
  envíos por estado, buscador (ID / SKU / búsqueda binaria por peso) e informe de validaciones.
- [x] Infraestructura de agentes: `memory-bank/`, `AGENTS.md`, `.agents/rules/` (3 reglas), `.agents/skills/` (1 skill).
- [x] `npm run verify` pasa (tipos + lint + build de ambas apps).

### En curso / pendiente de este hito

- [ ] Abrir PR de `hito4` hacia `main` y avisar al tech lead.

### Problemas conocidos

1. **`selectBestCarrier` puede recomendar un transportista que no puede entregar.** Según la spec de CONTEXT2, un transportista con
   puntuación ≥ 50 es "apto" y gana el más barato. Para el envío de ejemplo `SH-2024-8821` (Zaragoza → Madrid) el resultado es
   **UPS** (76,4 puntos, 30,89 US$), aunque UPS solo opera en EE. UU. El backoffice muestra la recomendación tal cual y añade un aviso
   de "Revisión manual" (`findHardConstraintIssues` en `uis/backoffice/lib/carrier-evaluation.ts`). **Propuesta**: confirmar con
   Carlos Vega / Ana Whitfield si país, peso, prioridad y fragilidad deben ser filtros eliminatorios y, si es así, cambiar
   `src/utils/transformations.ts` en una tarea propia.
2. Inconsistencia de CEO en `CONTEXT.md` (Thomas Harry vs Daniel Espinoza). Ver `projectbrief.md`.
3. El formulario `/aplicar` no envía datos a ningún sitio (igual que el Hito 1): muestra éxito en cliente. Necesita un endpoint en
   `services/` (Hito 5).

## Próximos pasos previstos

1. **Hito 5 — Backend**: crear `services/core-api` (inventario, envíos, transportistas) reutilizando los tipos de `src/types/models.ts`
   y sustituir `uis/backoffice/lib/sample-data.ts` por llamadas a esa API. Recibir también el formulario de `/aplicar`.
2. Añadir tests unitarios de `src/utils/*` (casos de CONTEXT2 + casos límite) y meterlos en `npm run verify`.
3. Backoffice: convertir las secciones del panel en rutas propias (`/inventario`, `/transportistas`, `/envios`) cuando tengan datos
   reales; los módulos "Próximo" del sidebar (Devoluciones, CX, Dashboard ejecutivo) esperan a sus hitos.
4. Evaluar mover los modelos de `src/types` a `packages/shared` cuando haya un segundo consumidor (API).

## Historial

- **2026-09-26 — Hito 4**: migrada la web del Hito 1 a `uis/website` (Next.js) y eliminados los HTML/JS estáticos (siguen en el
  historial de git, commit `33fc434`). Creado `uis/backoffice` con integración de `src/` vía alias + `turbopack.root`. Creados banco de
  memoria, `AGENTS.md`, reglas y skill `delivery-checklist`. Añadido `.gitignore` raíz y dejado de versionar `node_modules/` de la raíz.
  Backoffice en el puerto 3002 para no chocar con la API por defecto del tracker (3001).
- **Hito 3**: `uis/talent-pipeline-tracker` (PR #2).
- **Hito 2**: lógica de negocio en `src/` (PR #1).
