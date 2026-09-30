"use client";

import Link from "next/link";
import { useEffect } from "react";

interface ErrorFallbackProps {
  error: Error & { digest?: string };
  onRetry: () => void;
  title: string;
  description: string;
  /** Prefijo del log de consola: distingue el error de una vista del error crítico del layout. */
  logLabel: string;
  headingId?: string;
}

/**
 * Contenido común de `error.tsx` y `global-error.tsx`: nunca muestra el mensaje técnico,
 * solo la referencia (`digest`) para que soporte pueda localizar el error.
 */
export function ErrorFallback({
  error,
  onRetry,
  title,
  description,
  logLabel,
  headingId,
}: ErrorFallbackProps) {
  useEffect(() => {
    // Solo la referencia: el mensaje puede contener datos internos.
    console.error(logLabel, error.digest ?? error.name);
  }, [error, logLabel]);

  return (
    <>
      <h1 id={headingId} className="text-lg font-semibold text-slate-950">
        {title}
      </h1>
      <p className="mt-2 text-sm text-slate-600">{description}</p>
      <div className="mt-5 flex flex-wrap justify-center gap-3">
        <button
          type="button"
          onClick={onRetry}
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
    </>
  );
}
