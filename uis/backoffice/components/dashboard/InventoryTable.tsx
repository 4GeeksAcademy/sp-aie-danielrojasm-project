import type { Product } from "@trackflow/logic/types/models";
import { Badge } from "@/components/ui/Panel";
import {
  categoryLabels,
  formatUSD,
  productStatusLabels,
  warehouseLabels,
} from "@/lib/labels";

interface InventoryTableProps {
  products: Product[];
  lowStockSkus: Set<string>;
}

export function InventoryTable({ products, lowStockSkus }: InventoryTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="py-2 pr-3 font-medium">SKU</th>
            <th scope="col" className="py-2 pr-3 font-medium">Producto</th>
            <th scope="col" className="py-2 pr-3 font-medium">Almacén</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">Stock / mínimo</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">Valor</th>
            <th scope="col" className="py-2 font-medium">Estado</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {products.map((product) => {
            const isLow = lowStockSkus.has(product.sku);
            return (
              <tr key={product.sku}>
                <td className="py-2 pr-3 font-mono text-xs">{product.sku}</td>
                <td className="py-2 pr-3">
                  <span className="block text-slate-900">{product.name}</span>
                  <span className="text-xs text-slate-500">
                    {categoryLabels[product.category]}
                    {product.isFragile ? " · Frágil" : ""}
                  </span>
                </td>
                <td className="py-2 pr-3">{warehouseLabels[product.warehouse]}</td>
                <td className={`py-2 pr-3 text-right tabular-nums ${isLow ? "font-semibold text-amber-700" : ""}`}>
                  {product.stockQuantity} / {product.minStockThreshold}
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">
                  {formatUSD(product.stockQuantity * product.unitCostUSD)}
                </td>
                <td className="py-2">
                  {isLow ? (
                    <Badge tone={product.stockQuantity === 0 ? "danger" : "warning"}>
                      Reponer · {productStatusLabels[product.status]}
                    </Badge>
                  ) : (
                    <Badge tone="success">{productStatusLabels[product.status]}</Badge>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
