---
description: Reglas para leer o modificar la lógica de negocio del Hito 2 en src/ (funciones puras, spec de CONTEXT2, sin mutaciones).
trigger: model_decision
globs: "src/**/*.ts"
---

# Regla: lógica de negocio (`src/`)

**Alcance: solicitada por el agente** (`trigger: model_decision`). El agente debe cargarla cuando la tarea implique **leer para
reutilizar, cambiar o ampliar** algo de `src/` (modelos, scoring de transportistas, costes, validaciones), aunque el archivo que edite
esté en otra carpeta. `src/**` es zona protegida en `AGENTS.md`: modificarlo requiere confirmación explícita.

## Fuente de verdad

La especificación es `CONTEXT2.md` ("Funciones Requeridas" y "Reglas de Validación"). Si el código y la spec difieren, informa;
no "arregles" en silencio. Los problemas de diseño conocidos están en `memory-bank/progress.md` → "Problemas conocidos".

## Reglas

1. **Funciones puras**: solo usan sus parámetros; sin variables globales, sin `Date.now()` implícito, sin I/O, sin `console.log`.
2. **Sin mutaciones**: filtrar/ordenar sobre copias (`[...items].sort(...)`), nunca `items.sort(...)` sobre el argumento.
3. **Casos límite obligatorios**: arrays vacíos devuelven `[]`, `0` o `null` según la firma (nunca `NaN` ni excepción);
   `carrier: null` se ignora donde la spec lo diga.
4. **Redondeo** a 2 decimales con el helper existente `roundToTwoDecimals` en `transformations.ts`; no crees otro.
5. **Tipos**: reutiliza `src/types/models.ts`. Uniones de string literales (`"Standard" | "Express" | "Same-day"`), no `string`.
   Si añades un valor a una unión, actualiza también los `Record` de etiquetas de `uis/backoffice/lib/labels.ts`.
6. **Validaciones** devuelven `{ valid: boolean; errors: string[] }` con un mensaje por regla incumplida.
7. **Ubicación**: colecciones → `collections.ts`; búsqueda → `search.ts`; scoring, costes y agregaciones → `transformations.ts`;
   validaciones → `validations.ts`.
8. **Sin dependencias**: `src/` solo importa de `src/`. Debe compilar con `npm run check:ts` desde la raíz.

## Verificación

- `npm run check:ts` y `npm run build:uis` (el backoffice importa `src/`: un cambio de firma rompe el build) terminan con código 0.
- Con el dataset de CONTEXT2, `calculateShippingCost(SH-2024-8821, LAPTOP-DELL-15, SEUR)` = `46.22` y
  `scoreCarrierForShipment(SEUR, …)` = `97.6`. Si cambian sin que la tarea lo pida, es una regresión.
