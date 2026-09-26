---
description: Reglas para leer o modificar la lógica de negocio del Hito 2 en src/ (reglas de negocio, funciones puras, sin mutaciones).
trigger: model_decision
globs: "src/**/*.ts"
---

# Regla: lógica de negocio (`src/`)

## AI Engineering · 4Geeks Academy — Regla de agente de código

---

**Alcance:** a petición del agente (`trigger: model_decision`). El agente la carga cuando la tarea implica **leer para reutilizar, cambiar o
ampliar** algo de `src/` (modelos, puntuación de transportistas, costes, validaciones), aunque el archivo que edite esté en otra carpeta.

`src/` contiene la lógica de negocio del Hito 2, la que Ana Whitfield pidió "como si fuera a producción mañana" para procesar más de 2.000
envíos por semana. Es zona protegida en `AGENTS.md`: modificarla requiere confirmación explícita del desarrollador.

## Fuente de verdad

### 📐 Especificación del Hito 2

La especificación del Hito 2 son las reglas de negocio de esta sección y las firmas de `src/`. Si el código y estas reglas difieren, se
informa; no se "arregla" en silencio. Los problemas de diseño conocidos están en `memory-bank/progress.md`, en "Problemas conocidos".

- **Moneda y redondeo:** todo el dinero está en USD y los resultados se redondean a 2 decimales.
- **Stock bajo:** `stockQuantity ≤ minStockThreshold`.
- **Coste de envío:** `baseRateUSD + weightKg × ratePerKgUSD × quantity + distanceKm × ratePerKmUSD`, con recargo por prioridad
  (Standard +0 %, Express +30 %, Same-day +60 %).
- **Puntuación de transportista (0–100):** opera en el país de destino (20) + soporta el peso total (20) + acepta la prioridad (15) +
  fragilidad compatible (15) + `onTimeRate × 0,3` (30). Los cuatro criterios salen de `checkCarrierConstraints`.
- **Selección:** se descartan los transportistas por debajo de `CARRIER_SUITABILITY_THRESHOLD` (50) y gana el más barato del resto.
- **Validación de producto:** `sku` no vacío, peso en (0, 100], cada dimensión en (0, 200], stock y mínimo ≥ 0, coste unitario > 0.
- **Validación de envío:** `quantity` > 0, valor declarado > 0, distancia ≥ 0.
- **Validación de transportista:** tarifas ≥ 0, días de entrega > 0, `onTimeRate` entre 0 y 100, peso máximo > 0 y al menos un país.
- **Búsqueda:** por SKU sin distinguir mayúsculas; la búsqueda binaria por peso asume el array ordenado de forma ascendente y devuelve `-1`
  si no encuentra.

---

## Las reglas

### 🧪 Funciones puras

Solo usan sus parámetros: sin variables globales, sin `Date.now()` implícito, sin I/O y sin `console.log`.

---

### 🚫 Sin mutaciones

Se filtra y ordena sobre copias (`[...items].sort(...)`), nunca con `items.sort(...)` sobre el argumento.

---

### 🧱 Casos límite obligatorios

Los arrays vacíos devuelven `[]`, `0` o `null` según la firma, nunca `NaN` ni una excepción. `carrier: null` se ignora donde la
especificación lo dice.

---

### 🔢 Redondeo y tipos

El redondeo a 2 decimales usa el helper existente `roundToTwoDecimals` de `transformations.ts`; no se crea otro. Los tipos se reutilizan de
`src/types/models.ts`, con uniones de literales (`"Standard" | "Express" | "Same-day"`) en lugar de `string`. Si se añade un valor a una
unión, se actualizan también los `Record` de etiquetas de `uis/backoffice/lib/labels.ts`.

---

### ✔️ Validaciones

Devuelven `{ valid: boolean; errors: string[] }`, con un mensaje por cada regla incumplida.

---

### 🗂️ Ubicación y dependencias

Las colecciones van en `collections.ts`, la búsqueda en `search.ts`, la puntuación, los costes y las agregaciones en `transformations.ts`, y
las validaciones en `validations.ts`. `src/` solo importa de `src/` y debe compilar con `npm run check:ts` desde la raíz.

---

## Cómo comprobarla

- **Compilación:** `npm run check:ts` y `npm run build:uis` terminan con código 0. El backoffice importa `src/`, así que un cambio de firma
  rompe su build.
- **Valores de control:** con el envío de referencia `SH-2024-8821`, `calculateShippingCost(SH-2024-8821, LAPTOP-DELL-15, SEUR)` = `46.22` y
  `scoreCarrierForShipment(SEUR, …)` = `97.6`. Si cambian sin que la tarea lo pida, es una regresión.

---

_Documento interno — 4Geeks Academy · AI Engineering Track_
_Regla a petición del agente para la lógica de negocio de TrackFlow_
