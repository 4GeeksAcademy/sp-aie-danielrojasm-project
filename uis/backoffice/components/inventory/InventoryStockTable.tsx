"use client";

import { useMemo, useState } from "react";
import { History, PackageMinus, PackagePlus } from "lucide-react";
import {
  LOW_STOCK_THRESHOLD,
  getStockLevel,
  listSKUs,
  skuCategoryLabels,
  warehouseLabels,
  type SKU,
  type StockLevel,
  type Warehouse,
} from "@/lib/inventory";
import { useApiList } from "@/lib/use-api-list";
import { InventoryLinkButton } from "@/components/inventory/InventoryLinkButton";
import { InventoryPageHeader } from "@/components/inventory/InventoryPageHeader";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { StockLevelBadge } from "@/components/inventory/StockLevelBadge";

type WarehouseFilter = "all" | Warehouse;

const warehouses = Object.keys(warehouseLabels) as Warehouse[];

export function InventoryStockTable() {
  const { items: skus, loading, error: loadError, retry } = useApiList<SKU>(
    listSKUs,
    "No se pudo cargar el inventario.",
  );
  const [warehouse, setWarehouse] = useState<WarehouseFilter>("all");

  const visible = useMemo(
    () => (warehouse === "all" ? skus : skus.filter((sku) => sku.warehouse === warehouse)),
    [skus, warehouse],
  );

  const levelCounts = useMemo(() => {
    const counts: Record<StockLevel, number> = { out: 0, low: 0, healthy: 0 };
    for (const sku of visible) counts[getStockLevel(sku.current_stock)] += 1;
    return counts;
  }, [visible]);

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <InventoryPageHeader
        title="Stock por SKU"
        description="Stock disponible de cada SKU en su almacén, calculado como entradas menos salidas. Solo cambia registrando una entrada o una salida de stock."
        actions={
          <>
            <InventoryLinkButton href="/inventory/orders/inbound" variant="primary">
              <PackagePlus aria-hidden="true" className="h-4 w-4" />
              Registrar entrada
            </InventoryLinkButton>
            <InventoryLinkButton href="/inventory/orders/outbound">
              <PackageMinus aria-hidden="true" className="h-4 w-4" />
              Registrar salida
            </InventoryLinkButton>
            <InventoryLinkButton href="/inventory/orders">
              <History aria-hidden="true" className="h-4 w-4" />
              Historial
            </InventoryLinkButton>
          </>
        }
      />

      <section
        aria-labelledby="stock-list-title"
        className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="stock-list-title" className="text-lg font-semibold text-slate-900">
              SKUs en almacén
            </h2>
            <p className="mt-1 text-sm text-slate-500" aria-live="polite">
              {loading
                ? "Cargando inventario..."
                : loadError
                  ? "Sin datos"
                  : `${visible.length} SKUs · ${levelCounts.out} sin stock · ${levelCounts.low} con stock bajo`}
            </p>
          </div>
          <label htmlFor="stock-warehouse" className="text-xs font-medium text-slate-600">
            Almacén
            <select
              id="stock-warehouse"
              value={warehouse}
              onChange={(event) => setWarehouse(event.target.value as WarehouseFilter)}
              className="mt-1 block rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option value="all">Todos</option>
              {warehouses.map((item) => (
                <option key={item} value={item}>
                  {warehouseLabels[item]}
                </option>
              ))}
            </select>
          </label>
        </div>

        <p className="mt-3 text-xs text-slate-500">
          Niveles: <span className="font-semibold text-emerald-700">saludable</span> con{" "}
          {LOW_STOCK_THRESHOLD} unidades o más, <span className="font-semibold text-amber-700">bajo</span>{" "}
          por debajo de {LOW_STOCK_THRESHOLD} y <span className="font-semibold text-rose-700">sin stock</span>{" "}
          con 0.
        </p>

        {loading ? (
          <div aria-busy="true" className="mt-5 space-y-2">
            <p className="sr-only" role="status">
              Cargando inventario...
            </p>
            {Array.from({ length: 5 }, (_, index) => (
              <div key={index} className="h-14 animate-pulse rounded-lg bg-slate-100" />
            ))}
          </div>
        ) : null}

        {!loading && loadError ? (
          <div className="mt-5">
            <RetryAlert message={loadError} onRetry={retry} />
          </div>
        ) : null}

        {!loading && !loadError ? (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[880px] text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-3 py-3">SKU</th>
                  <th scope="col" className="px-3 py-3">Cliente</th>
                  <th scope="col" className="px-3 py-3">Categoría</th>
                  <th scope="col" className="px-3 py-3">Almacén</th>
                  <th scope="col" className="px-3 py-3">Stock actual</th>
                  <th scope="col" className="px-3 py-3">Registrar</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visible.map((sku) => (
                  <tr key={sku.id}>
                    <td className="px-3 py-4">
                      <p className="font-mono text-xs font-semibold text-slate-900">{sku.sku}</p>
                      <p className="mt-1 text-slate-700">{sku.name}</p>
                    </td>
                    <td className="px-3 py-4 text-slate-700">{sku.client_name}</td>
                    <td className="px-3 py-4 text-slate-700">{skuCategoryLabels[sku.category]}</td>
                    <td className="whitespace-nowrap px-3 py-4 text-slate-700">
                      {warehouseLabels[sku.warehouse]}
                    </td>
                    <td className="px-3 py-4">
                      <StockLevelBadge stock={sku.current_stock} />
                    </td>
                    <td className="px-3 py-4">
                      <div className="flex gap-2">
                        <InventoryLinkButton
                          href={`/inventory/orders/inbound?sku=${sku.id}`}
                          size="sm"
                          ariaLabel={`Registrar entrada de stock de ${sku.sku}`}
                        >
                          <PackagePlus aria-hidden="true" className="h-3.5 w-3.5" />
                          Entrada
                        </InventoryLinkButton>
                        <InventoryLinkButton
                          href={`/inventory/orders/outbound?sku=${sku.id}`}
                          size="sm"
                          ariaLabel={`Registrar salida de stock de ${sku.sku}`}
                        >
                          <PackageMinus aria-hidden="true" className="h-3.5 w-3.5" />
                          Salida
                        </InventoryLinkButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {visible.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-500">
                {skus.length === 0
                  ? "Todavía no hay SKUs registrados en el inventario."
                  : "No hay SKUs en este almacén."}
              </p>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}
