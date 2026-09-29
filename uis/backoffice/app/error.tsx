"use client";

import Link from "next/link";
import { useEffect } from "react";

interface RouteErrorProps {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}

/** Límite de error de las vistas internas: nunca muestra el mensaje técnico. */
export default function RouteError({ error, unstable_retry }: RouteErrorProps) {
  useEffect(() => {
    // Solo la referencia: el mensaje puede contener datos internos.
    console.error("Error de interfaz en el backoffice", error.digest ?? error.name);
  }, [error]);

  return (
    <section
      role="alert"
      aria-labelledby="route-error-title"
      className="mx-auto mt-10 max-w-lg rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm"
    >
      <h1 id="route-error-title" className="text-lg font-semibold text-slate-950">
        No se pudo mostrar esta sección
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        Se produjo un error inesperado. Puedes reintentarlo o volver al panel de
        operaciones.
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-3">
        <button
          type="button"
          onClick={() => unstable_retry()}
          className="h-10 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800"
        >
          Reintentar
        </button>
        <Link
          href="/"
          className="inline-flex h-10 items-center rounded-md border border-slate-300 px-4 text-sm font-semibold text-slate-800 hover:bg-slate-50"
        >
          Ir al panel de operaciones
        </Link>
      </div>
      <p className="mt-5 text-xs text-slate-500">
        Si el problema continúa, avisa al equipo de TrackFlow Tech
        {error.digest ? ` indicando la referencia ${error.digest}` : ""}.
      </p>
    </section>
  );
}
