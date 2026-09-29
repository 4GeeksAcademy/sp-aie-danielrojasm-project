"use client";

import { useEffect, useState } from "react";
import { getUserMessage } from "@/lib/api-client";
import { listSKUs, type SKU } from "@/lib/inventory";

interface SkuCatalog {
  skus: SKU[];
  loading: boolean;
  error: string;
  retry: () => void;
}

/** Carga los SKUs para los selectores de los formularios de movimientos. */
export function useSkuCatalog(): SkuCatalog {
  const [skus, setSkus] = useState<SKU[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const loaded = await listSKUs();
        if (active) setSkus(Array.isArray(loaded) ? loaded : []);
      } catch (loadError) {
        if (active) {
          setSkus([]);
          setError(getUserMessage(loadError, "No se pudo cargar la lista de SKUs."));
        }
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [attempt]);

  return { skus, loading, error, retry: () => setAttempt((value) => value + 1) };
}
