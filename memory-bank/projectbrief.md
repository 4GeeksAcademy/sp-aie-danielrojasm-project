# Project brief — TrackFlow Tech

> Contexto de negocio. Fuente de verdad: `CONTEXT.md` (empresa), `CONTEXT2.md` (Hito 2), `Context3.md` (Hito 3).
> Si este archivo contradice esas fuentes, ganan ellas: corrige este archivo.

## La empresa

**TrackFlow** es una empresa de logística de última milla y gestión de almacenes (fundada en 2009, ~130 empleados, ~9 M€/año).
Opera en **Estados Unidos y España** con dos almacenes: **Los Ángeles** y **Zaragoza**. Para sus clientes (marcas de e-commerce)
almacena inventario, prepara pedidos, los entrega mediante **8 transportistas** (UPS, FedEx, DHL en EE. UU.; MRW, SEUR, DHL en
España; más dos locales) y gestiona devoluciones (**18–25 %** del volumen).

**TrackFlow Tech** es la unidad interna que construye sistemas, integraciones y automatizaciones. Este monorepo es su núcleo técnico.

## Personas clave

| Persona | Rol | Qué espera de nosotros |
| --- | --- | --- |
| Ana Whitfield | Directora de Operaciones de Almacén (~70 operarios) | Inventario unificado entre almacenes, alertas de stock bajo, código "listo para producción" (Hito 2) y la herramienta de candidaturas (Hito 3) |
| Carlos Vega | Última milla y transportistas | Motor de selección de transportista explicable, tracking unificado |
| Sofía Ramos | Logística inversa | Aprobación automática de devoluciones con reglas por cliente |
| Valentina Cruz | Atención al cliente (15 agentes) | Agente de CX, base de conocimiento RAG, tickets |
| Miguel Torres | Comercial | CRM, informes PDF automáticos, riesgo de renovación |
| Andrés Kim | CTO (Zaragoza) | Telemetría, pipeline de datos, monitorización |
| Thomas Harry | Fundador y CEO | Dashboard ejecutivo con KPIs por país, informe semanal automático |

> ⚠️ Inconsistencia en `CONTEXT.md`: la cabecera nombra CEO a **Thomas Harry**, pero la sección "Dirección Ejecutiva" nombra a
> **Daniel Espinoza**. Hasta que se confirme, usa "Thomas Harry (fundador y CEO)" en textos públicos y no inventes un tercero.

## Problema que resolvemos

La operación de dos países funciona con herramientas desconectadas:

- Los dos almacenes usan SGA distintos (uno comercial, otro una hoja de cálculo) y **no comparten inventario**.
- Los pedidos llegan por email y se transcriben a mano; el picking es en papel; las discrepancias se detectan tarde.
- La asignación de transportista es manual y **no hay datos históricos** (tasa a tiempo, coste por kg, incidencias por ruta).
- Cada devolución pasa por revisión humana; las consultas de CX se responden con un Word en Google Drive; no hay cobertura 24/7.
- El CEO decide con un informe que los directores montan a mano cada domingo (3–4 h por director, datos con 1–2 días de retraso).

## KPIs del negocio (y dónde viven en el código)

| KPI | Origen hoy | Módulo que lo calcula / mostrará |
| --- | --- | --- |
| Valor de inventario y SKUs bajo mínimo | Datos de ejemplo | `src/utils/transformations.ts` (`calculateTotalInventoryValue`), `src/utils/collections.ts` (`filterLowStockProducts`) → `uis/backoffice` |
| Coste y puntuación por transportista | Datos de ejemplo | `calculateShippingCost`, `scoreCarrierForShipment`, `selectBestCarrier` → simulador del backoffice |
| Tasa de entrega a tiempo | `Carrier.onTimeRate` | `sortCarriersByReliability` → ranking del backoffice; web pública muestra "98.1 % entregas a tiempo" (cifra de marketing) |
| Envíos por estado / transportistas más usados | Datos de ejemplo | `groupShipmentsByStatus`, `findTopCarriers` |
| Tasa de devoluciones | — | Pendiente (hito de backend/telemetría) |
| Satisfacción de cliente | — | Pendiente (agente de CX) |

## Objetivos del proyecto (por hitos)

1. **Hito 1 — Web corporativa**: landing + formulario de aplicación B2B. Hoy vive en `uis/website` (Next.js).
2. **Hito 2 — Lógica de negocio** en TypeScript puro (`src/`): modelos, filtros, búsqueda, scoring, costes, validaciones.
3. **Hito 3 — Talent Pipeline Tracker** (`uis/talent-pipeline-tracker`): candidaturas para Asistente de Dirección en Zaragoza.
4. **Hito 4 — Monorepo AI-ready** (actual): banco de memoria, `AGENTS.md`, reglas y skills en `.agents/`, web en Next.js y backoffice.
5. Próximos: API central en `services/` (Hito 5), telemetría (6), RAG (7), agentes (8), workflows n8n (9), tiempo real (10).

## Restricciones de negocio que el código debe respetar

- Dos países y dos idiomas: la UI es **en español**; los valores de dominio en inglés (`"In transit"`, `in_progress`…) **nunca** se
  muestran crudos, siempre con etiqueta legible (regla explícita del Hito 3, extendida a todo el monorepo).
- Monedas: el modelo del Hito 2 trabaja en **USD** (`unitCostUSD`, `baseRateUSD`…). No mezclar EUR sin conversión explícita.
- Ana procesa **>2.000 envíos/semana**: nada de lógica que se rompa con arrays vacíos, `null` o datos inválidos.
- Las notas internas de candidatos solo se ven en el detalle (Hito 3).
