# TrackFlow — backoffice (`uis/backoffice`)

Aplicación interna de TrackFlow Tech para la lógica operativa de la empresa. Layout propio (sidebar + barra superior),
independiente de la web pública.

La ruta `/` es el **panel de operaciones**: muestra en pantalla la salida del módulo de lógica de negocio del **Hito 2**
(`<repo>/src`), importado desde su ubicación original, sin copias.

| Sección del panel | Funciones del Hito 2 |
| --- | --- |
| KPIs | `calculateTotalInventoryValue`, `filterLowStockProducts`, `calculateAverageShipmentDistance` |
| Inventario por stock | `sortProductsByStock`, `filterLowStockProducts` |
| Distribución | `filterProductsByWarehouse`, `countProductsByCategory` |
| Selección de transportista (interactivo) | `scoreCarrierForShipment`, `calculateShippingCost`, `selectBestCarrier`, `findProductBySKU`, `validateShipment` |
| Ranking de fiabilidad | `sortCarriersByReliability` |
| Envíos por estado | `groupShipmentsByStatus`, `findTopCarriers` |
| Búsqueda de registros | `findShipmentById`, `findProductBySKU`, `binarySearchProductByWeight` |
| Calidad de datos | `validateProduct`, `validateShipment`, `validateCarrier` |

## Ejecutar

```bash
cd uis/backoffice
npm install
npm run dev        # http://localhost:3002
```

Puerto 3002 a propósito: el tracker del Hito 3 usa `http://localhost:3001` como API por defecto.

## Cómo se importa `src/`

- `tsconfig.json` → `"@trackflow/logic/*": ["../../src/*"]`
- `next.config.ts` → `turbopack.root` y `outputFileTracingRoot` = raíz del monorepo (Turbopack no resuelve fuera de su raíz).

```ts
import { selectBestCarrier } from "@trackflow/logic/utils/transformations";
import type { Product } from "@trackflow/logic/types/models";
```

## Estructura

```text
app/                 layout interno y panel (/)
components/layout/   Sidebar, TopBar
components/dashboard/ CarrierSimulator, RecordLookup (cliente), InventoryTable, CarrierEvaluationTable, ValidationReport
components/ui/       Panel, KpiCard, Badge
lib/sample-data.ts   dataset de CONTEXT2 ampliado (se sustituirá por la API de services/)
lib/labels.ts        etiquetas en español de los valores de dominio
lib/carrier-evaluation.ts  adaptador de scoring/coste para la tabla + avisos de restricciones duras
```
