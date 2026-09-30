"use client";

import { listSKUs, type SKU } from "@/lib/inventory";
import { useApiList } from "@/lib/use-api-list";

interface SkuCatalog {
  skus: SKU[];
  loading: boolean;
  error: string;
  retry: () => void;
}

/** Carga los SKUs para los selectores de los formularios de movimientos. */
export function useSkuCatalog(): SkuCatalog {
  const { items, loading, error, retry } = useApiList<SKU>(
    listSKUs,
    "No se pudo cargar la lista de SKUs.",
  );
  return { skus: items, loading, error, retry };
}
