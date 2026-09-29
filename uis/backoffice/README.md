# Backoffice de TrackFlow

## AI Engineering · 4Geeks Academy — `uis/backoffice`

---

El backoffice es la aplicación interna de TrackFlow Tech, donde irá creciendo toda la lógica operativa de la empresa: inventario,
transportistas, envíos y, en próximos hitos, devoluciones, atención al cliente y el dashboard ejecutivo. Tiene su propio layout (sidebar y
barra superior), independiente de la web pública.

Su ruta `/` es el **panel de operaciones**, que muestra en pantalla la salida de la lógica de negocio del **Hito 2**. Esa lógica se importa
desde `<repo>/src`, su ubicación original, sin copias.

**Tecnología:** Next.js 16.2.10 · React 19 · TypeScript 5 · Tailwind CSS 4
**Puerto de desarrollo:** 3002. No usa el 3001 porque el tracker del Hito 3 lo usa como API por defecto.

## El panel de operaciones

### 📊 KPIs

Valor total de inventario, SKUs bajo stock mínimo, distancia media por envío y registros con errores.

**Funciones:** `calculateTotalInventoryValue`, `filterLowStockProducts`, `calculateAverageShipmentDistance`

---

### 🚚 Inventario y distribución

Productos ordenados de menor a mayor stock, con los que hay que reponer marcados, y su reparto por almacén y categoría.

**Funciones:** `sortProductsByStock`, `filterLowStockProducts`, `filterProductsByWarehouse`, `countProductsByCategory`

---

### 📦 Selección de transportista (interactivo)

Simulador que parte del envío `SH-2024-8821` (Zaragoza → Madrid). Al cambiar producto, país, prioridad, unidades o distancia, recalcula la
puntuación y el coste de cada transportista y muestra el recomendado. Si la recomendación incumple una restricción operativa (por ejemplo,
que el transportista no opere en el país de destino), añade un aviso de revisión manual.

**Funciones:** `scoreCarrierForShipment`, `calculateShippingCost`, `selectBestCarrier`, `findProductBySKU`, `validateShipment`

---

### 🏆 Fiabilidad y envíos

Ranking de transportistas por entrega a tiempo, envíos agrupados por estado y transportistas más usados.

**Funciones:** `sortCarriersByReliability`, `groupShipmentsByStatus`, `findTopCarriers`

---

### 🔎 Búsqueda de registros

Búsqueda de un envío por ID, de un producto por SKU y de un producto por peso mediante búsqueda binaria.

**Funciones:** `findShipmentById`, `findProductBySKU`, `binarySearchProductByWeight`

---

### ✔️ Calidad de datos

Informe de los productos, envíos y transportistas que no superan las reglas de negocio y que se bloquearían antes de procesar un pedido.

**Funciones:** `validateProduct`, `validateShipment`, `validateCarrier`

---

## Cómo ejecutarlo

```bash
cd uis/backoffice
npm install
npm run dev        # http://localhost:3002
```

---

## Cómo se importa `src/`

**Alias en `tsconfig.json`:** `"@trackflow/logic/*": ["../../src/*"]`

**En `next.config.ts`:** `turbopack.root` y `outputFileTracingRoot` apuntan a la raíz del monorepo, porque Turbopack no resuelve archivos
fuera de su raíz.

```ts
import { selectBestCarrier } from "@trackflow/logic/utils/transformations";
import type { Product } from "@trackflow/logic/types/models";
```

---

## Estructura

- **`app/`** — layout interno y panel (`/`).
- **`components/layout/`** — `Sidebar` y `TopBar`.
- **`components/dashboard/`** — `CarrierSimulator` y `RecordLookup` (cliente), `InventoryTable`, `CarrierEvaluationTable` y
  `ValidationReport`.
- **`components/ui/`** — `Panel`, `KpiCard` y `Badge`.
- **`lib/sample-data.ts`** — dataset de referencia del Hito 2 ampliado. Se sustituirá por la API de `services/`.
- **`lib/labels.ts`** — etiquetas en español de los valores de dominio.
- **`lib/carrier-evaluation.ts`** — adaptador de puntuación y coste para la tabla, con los avisos de restricciones duras.

---

_Documento interno — 4Geeks Academy · AI Engineering Track_
_Interfaz interna de TrackFlow · Hito 4_
