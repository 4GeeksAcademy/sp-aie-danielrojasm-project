"use client";

import Link from "next/link";
import { useEffect } from "react";
import { reportFrontendError } from "@/lib/telemetry-reporters";

interface ErrorFallbackProps {
  error: Error & { digest?: string };
  onRetry: () => void;
  title: string;
  description: string;
  /** Prefijo del log de consola: distingue el error de una vista del error crítico del layout. */
  logLabel: string;
  /** Límite que capturó el error: el de una vista (`route`) o el del layout (`global`). */
  boundary: "route" | "global";
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
  boundary,
  headingId,
}: ErrorFallbackProps) {
  useEffect(() => {
    // Solo la referencia: el mensaje puede contener datos internos.
    console.error(logLabel, error.digest ?? error.name);
    reportFrontendError(error, boundary);
  }, [error, logLabel, boundary]);

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
