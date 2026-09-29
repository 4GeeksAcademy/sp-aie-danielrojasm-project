"use client";

import Link from "next/link";
import { useEffect } from "react";

interface RouteErrorProps {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}

export default function RouteError({ error, unstable_retry }: RouteErrorProps) {
  useEffect(() => {
    // Solo la referencia: el mensaje puede contener datos internos.
    console.error("Error de interfaz en el tracker", error.digest ?? error.name);
  }, [error]);

  return (
    <section
      role="alert"
      aria-labelledby="route-error-title"
      className="mx-auto mt-10 w-full max-w-lg rounded-2xl border border-rose-300/40 bg-slate-950/90 p-6 text-center text-slate-100"
    >
      <h1 id="route-error-title" className="text-xl font-bold text-white">
        No se pudo mostrar esta página
      </h1>
      <p className="mt-2 text-sm text-slate-300">
        Se produjo un error inesperado. Reintenta o vuelve al listado de candidaturas.
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
          Volver al listado
        </Link>
      </div>
      <p className="mt-5 text-xs text-slate-400">
        Si el problema continúa, avisa al equipo de People &amp; Talent
        {error.digest ? ` indicando la referencia ${error.digest}` : ""}.
      </p>
    </section>
  );
}
