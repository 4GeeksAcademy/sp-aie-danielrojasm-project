"use client";

import { useEffect, useEffectEvent, useState, type Dispatch, type SetStateAction } from "react";
import { getUserMessage } from "@/lib/api-client";

export interface ApiList<T> {
  items: T[];
  /** Para reflejar en local una alta o edición confirmada por la API sin recargar. */
  setItems: Dispatch<SetStateAction<T[]>>;
  loading: boolean;
  /** Mensaje legible del último fallo de carga; vacío si no lo hay. */
  error: string;
  retry: () => void;
}

/**
 * Carga una lista de la API con estado de carga, error legible y reintento.
 * Descarta respuestas que llegan tras desmontar o tras un cambio de `key`, y
 * trata una respuesta que no es un array como lista vacía.
 *
 * @param load Petición a la API; puede cambiar en cada render.
 * @param fallbackMessage Mensaje si el error no trae uno propio para el usuario.
 * @param key Vuelve a cargar cuando cambia (p. ej. los filtros de la consulta).
 */
export function useApiList<T>(
  load: () => Promise<T[]>,
  fallbackMessage: string,
  key = "",
): ApiList<T> {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const loadItems = useEffectEvent(load);
  const toMessage = useEffectEvent((loadError: unknown) => getUserMessage(loadError, fallbackMessage));

  useEffect(() => {
    let active = true;
    const run = async () => {
      setLoading(true);
      setError("");
      try {
        const loaded = await loadItems();
        if (active) setItems(Array.isArray(loaded) ? loaded : []);
      } catch (loadError) {
        if (active) {
          setItems([]);
          setError(toMessage(loadError));
        }
      } finally {
        if (active) setLoading(false);
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [key, attempt]);

  return { items, setItems, loading, error, retry: () => setAttempt((value) => value + 1) };
}
