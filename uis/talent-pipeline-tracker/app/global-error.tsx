"use client";

import Link from "next/link";
import { useEffect } from "react";
import "./globals.css";

interface GlobalErrorProps {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}

export default function GlobalError({ error, unstable_retry }: GlobalErrorProps) {
  useEffect(() => {
    console.error("Error crítico en el tracker", error.digest ?? error.name);
  }, [error]);

  return (
    <html lang="es">
      <body className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-100">
        <title>Error | Talent Pipeline Tracker</title>
        <main role="alert" className="max-w-lg text-center">
          <h1 className="text-xl font-bold text-white">El tracker no se pudo cargar</h1>
          <p className="mt-2 text-sm text-slate-300">
            Se produjo un error inesperado. Vuelve a intentarlo en unos instantes.
          </p>
          <div className="mt-5 flex flex-wrap justify-center gap-3">
            <button
              type="button"
              onClick={() => unstable_retry()}
              className="rounded-lg bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-200"
            >
              Reintentar
            </button>
            <Link
              href="/"
              className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-semibold text-slate-100 hover:border-cyan-200"
            >
              Ir al listado
            </Link>
          </div>
        </main>
      </body>
    </html>
  );
}
