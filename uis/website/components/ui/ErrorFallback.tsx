"use client";

import Link from "next/link";
import { useEffect } from "react";
import { company } from "@/content/site";

interface ErrorFallbackProps {
  error: Error & { digest?: string };
  onRetry: () => void;
  title: string;
  description: string;
  /** Prefijo del log de consola: distingue el error de una página del error crítico del layout. */
  logLabel: string;
  headingId?: string;
}

/** Contenido común de `error.tsx` y `global-error.tsx`: reintento, vuelta al inicio y contacto. */
export function ErrorFallback({
  error,
  onRetry,
  title,
  description,
  logLabel,
  headingId,
}: ErrorFallbackProps) {
  useEffect(() => {
    console.error(logLabel, error.digest ?? error.name);
  }, [error, logLabel]);

  return (
    <>
      <h1 id={headingId} className="text-2xl font-bold text-white">
        {title}
      </h1>
      <p className="mt-3 text-slate-300">{description}</p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md bg-cyan-300 px-5 py-2.5 font-semibold text-slate-950 hover:bg-cyan-200"
        >
          Reintentar
        </button>
        <Link
          href="/"
          className="rounded-md border border-slate-600 px-5 py-2.5 font-semibold text-white hover:border-cyan-300"
        >
          Ir al inicio
        </Link>
      </div>
      <p className="mt-8 text-sm text-slate-400">
        Si el problema continúa, escríbenos a{" "}
        <a href={`mailto:${company.email}`} className="text-cyan-300 underline">
          {company.email}
        </a>
        .
      </p>
    </>
  );
}
