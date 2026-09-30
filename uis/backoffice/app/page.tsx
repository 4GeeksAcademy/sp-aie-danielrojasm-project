import {
  filterLowStockProducts,
  filterProductsByWarehouse,
  sortCarriersByReliability,
  sortProductsByStock,
} from "@trackflow/logic/utils/collections";
import {
  calculateAverageShipmentDistance,
  calculateTotalInventoryValue,
  countProductsByCategory,
  findTopCarriers,
  groupShipmentsByStatus,
} from "@trackflow/logic/utils/transformations";
import {
  validateCarrier,
  validateProduct,
  validateShipment,
} from "@trackflow/logic/utils/validations";
import type {
  ProductCategory,
  ShipmentStatus,
  WarehouseLocation,
} from "@trackflow/logic/types/models";
import { InventoryTable } from "@/components/dashboard/InventoryTable";
import { LazyCarrierSimulator } from "@/components/dashboard/LazyCarrierSimulator";
import { RecordLookup } from "@/components/dashboard/RecordLookup";
import {
  ValidationReport,
  type ValidationRow,
} from "@/components/dashboard/ValidationReport";
import { Badge, KpiCard, Panel } from "@/components/ui/Panel";
import {
  categoryLabels,
  formatNumber,
  formatUSD,
  shipmentStatusLabels,
  warehouseLabels,
} from "@/lib/labels";
import {
  sampleCarriers,
  sampleProducts,
  sampleShipments,
} from "@/lib/sample-data";

const WAREHOUSES: WarehouseLocation[] = ["Los Angeles", "Zaragoza"];

export default function OperationsDashboardPage() {
  // Solo los productos válidos entran en inventario y métricas; los inválidos
  // se reportan en "Calidad de datos".
  const productChecks = sampleProducts.map((product) => ({
    product,
    result: validateProduct(product),
  }));
  const shipmentChecks = sampleShipments.map((shipment) => ({
    shipment,
    result: validateShipment(shipment),
  }));

  const products = productChecks.filter((c) => c.result.valid).map((c) => c.product);
  const shipments = shipmentChecks.filter((c) => c.result.valid).map((c) => c.shipment);

  // --- Lógica de negocio del Hito 2 (importada desde /src) ---
  const inventoryValue = calculateTotalInventoryValue(products);
  const lowStock = filterLowStockProducts(products);
  const productsByStock = sortProductsByStock(products, "asc");
  const productsByWeight = [...products].sort((a, b) => a.weightKg - b.weightKg);
  const categoryCounts = countProductsByCategory(products);
  const carriersByReliability = sortCarriersByReliability(sampleCarriers, "desc");
  const shipmentsByStatus = groupShipmentsByStatus(shipments);
  const topCarriers = findTopCarriers(shipments, 3);
  const averageDistance = calculateAverageShipmentDistance(shipments);

  const validationRows: ValidationRow[] = [
    ...productChecks.map(({ product, result }) => ({
      entity: "Producto" as const,
      reference: product.sku || `(sin SKU) ${product.name}`,
      ...result,
    })),
    ...shipmentChecks.map(({ shipment, result }) => ({
      entity: "Envío" as const,
      reference: shipment.id,
      ...result,
    })),
    ...sampleCarriers.map((carrier) => ({
      entity: "Transportista" as const,
      reference: carrier.id,
      ...validateCarrier(carrier),
    })),
  ];
  const invalidCount = validationRows.filter((row) => !row.valid).length;

  const initialShipment = sampleShipments[0];

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          Panel de operaciones
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Vista de entrada del backoffice de TrackFlow. Todas las cifras se
          calculan en tiempo de render con el módulo de lógica de negocio del
          Hito 2 (<code className="font-mono text-xs">src/utils</code>), importado
          sin copias.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Valor total de inventario"
          value={formatUSD(inventoryValue)}
          hint={`${products.length} SKUs en 2 almacenes`}
        />
        <KpiCard
          label="SKUs bajo stock mínimo"
          value={String(lowStock.length)}
          hint="stockQuantity ≤ minStockThreshold"
          tone={lowStock.length > 0 ? "warning" : "default"}
        />
        <KpiCard
          label="Distancia media por envío"
          value={`${formatNumber(averageDistance)} km`}
          hint={`${shipments.length} envíos válidos`}
        />
        <KpiCard
          label="Registros con errores"
          value={String(invalidCount)}
          hint="Bloqueados por las validaciones"
          tone={invalidCount > 0 ? "danger" : "default"}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        {/* min-w-0: sin él, el grid ensancha la columna al min-width de la tabla y la página se desborda en móvil. */}
        <div className="min-w-0 xl:col-span-2">
          <Panel
            id="inventario"
            title="Inventario por nivel de stock"
            description="Ordenado de menor a mayor stock; los SKUs a reponer aparecen primero."
            source="sortProductsByStock · filterLowStockProducts"
          >
            <InventoryTable
              products={productsByStock}
              lowStockSkus={new Set(lowStock.map((product) => product.sku))}
            />
          </Panel>
        </div>
        <Panel
          title="Distribución"
          source="filterProductsByWarehouse · countProductsByCategory"
        >
          <dl className="grid grid-cols-2 gap-3">
            {WAREHOUSES.map((warehouse) => (
              <div key={warehouse} className="rounded-lg bg-slate-50 p-3">
                <dt className="text-xs text-slate-500">{warehouseLabels[warehouse]}</dt>
                <dd className="text-xl font-semibold tabular-nums">
                  {filterProductsByWarehouse(products, warehouse).length} SKUs
                </dd>
              </div>
            ))}
          </dl>
          <ul className="mt-4 space-y-2 text-sm">
            {(Object.keys(categoryCounts) as ProductCategory[]).map((category) => (
              <li key={category} className="flex items-center justify-between">
                <span>{categoryLabels[category]}</span>
                <span className="tabular-nums text-slate-600">{categoryCounts[category]}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <Panel
        id="transportistas"
        title="Selección de transportista"
        description={`Simulador partiendo del envío ${initialShipment.id} (Zaragoza → Madrid). Cambia los parámetros para recalcular puntuación y coste.`}
        source="scoreCarrierForShipment · calculateShippingCost · selectBestCarrier"
      >
        <LazyCarrierSimulator
          products={products}
          carriers={sampleCarriers}
          initialShipment={initialShipment}
        />
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel
          title="Ranking de fiabilidad"
          description="Tasa de entrega a tiempo por transportista."
          source="sortCarriersByReliability"
        >
          <ol className="space-y-2 text-sm">
            {carriersByReliability.map((carrier, index) => (
              <li key={carrier.id} className="flex items-center gap-3">
                <span className="w-5 text-right text-slate-400">{index + 1}</span>
                <span className="w-28 font-medium">{carrier.name}</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                  <div className="h-full rounded-full bg-cyan-600" style={{ width: `${carrier.onTimeRate}%` }} />
                </div>
                <span className="w-12 text-right tabular-nums">{carrier.onTimeRate}%</span>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel
          id="envios"
          title="Envíos por estado"
          source="groupShipmentsByStatus · findTopCarriers"
        >
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {(Object.keys(shipmentsByStatus) as ShipmentStatus[]).map((status) => (
              <li key={status} className="rounded-lg bg-slate-50 p-3">
                <p className="text-xs text-slate-500">{shipmentStatusLabels[status]}</p>
                <p className="text-xl font-semibold tabular-nums">{shipmentsByStatus[status].length}</p>
              </li>
            ))}
          </ul>
          <h3 className="mt-5 text-sm font-semibold text-slate-700">Transportistas más usados</h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {topCarriers.map((item) => (
              <li key={item.carrier}>
                <Badge tone="info">
                  {item.carrier} · {item.count} envío{item.count === 1 ? "" : "s"}
                </Badge>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel
          title="Búsqueda de registros"
          source="findShipmentById · findProductBySKU · binarySearchProductByWeight"
        >
          <RecordLookup
            products={products}
            productsByWeight={productsByWeight}
            shipments={shipments}
          />
        </Panel>

        <Panel
          id="validaciones"
          title="Calidad de datos"
          source="validateProduct · validateShipment · validateCarrier"
        >
          <ValidationReport rows={validationRows} />
        </Panel>
      </div>
    </div>
  );
}
