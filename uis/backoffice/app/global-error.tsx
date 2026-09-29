"use client";

import Link from "next/link";
import { useEffect } from "react";
import "./globals.css";

interface GlobalErrorProps {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}

/** Sustituye al layout raíz si este falla (p. ej. el proveedor de sesión). */
export default function GlobalError({ error, unstable_retry }: GlobalErrorProps) {
  useEffect(() => {
    console.error("Error crítico en el backoffice", error.digest ?? error.name);
  }, [error]);

  return (
    <html lang="es">
      <body className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-900">
        <title>Error | Backoffice TrackFlow</title>
        <main role="alert" className="w-full max-w-md rounded-xl bg-white p-6 text-center shadow-xl">
          <h1 className="text-lg font-semibold text-slate-950">El backoffice no se pudo cargar</h1>
          <p className="mt-2 text-sm text-slate-600">
            Se produjo un error inesperado. Reintenta o vuelve a la página principal.
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
              Ir a la página principal
            </Link>
          </div>
          <p className="mt-5 text-xs text-slate-500">
            Si el problema continúa, avisa al equipo de TrackFlow Tech
            {error.digest ? ` indicando la referencia ${error.digest}` : ""}.
          </p>
        </main>
      </body>
    </html>
  );
}
