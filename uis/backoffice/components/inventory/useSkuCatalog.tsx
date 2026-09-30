"use client";

import { useMemo, type ReactNode } from "react";
import { formatSKUOption, listSKUs, type SKUListItem } from "@/lib/inventory";
import { useApiList } from "@/lib/use-api-list";

interface SkuCatalog {
  skus: SKUListItem[];
  /** Un `<option>` por SKU, estable mientras no cambie el catálogo. */
  options: ReactNode;
  loading: boolean;
  error: string;
  retry: () => void;
}

/** Carga los SKUs para los selectores de los formularios de movimientos. */
export function useSkuCatalog(): SkuCatalog {
  const { items, loading, error, retry } = useApiList<SKUListItem>(
    listSKUs,
    "No se pudo cargar la lista de SKUs.",
  );
  // Los formularios se re-renderizan en cada pulsación (cantidad, referencia,
  // tracking) y el catálogo solo cambia al cargarse. Con los mismos elementos,
  // React se salta el diff de las opciones: con 1.200 SKUs era la mayor parte
  // del trabajo de cada pulsación (ver audit/caching/CACHING_REPORT.md).
  const options = useMemo(
    () =>
      items.map((sku) => (
        <option key={sku.id} value={sku.id}>
          {formatSKUOption(sku)}
        </option>
      )),
    [items],
  );
  return { skus: items, options, loading, error, retry };
}
