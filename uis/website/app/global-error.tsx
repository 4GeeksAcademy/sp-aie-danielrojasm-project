"use client";

import Link from "next/link";
import { useEffect } from "react";
import { company } from "@/content/site";
import "./globals.css";

interface GlobalErrorProps {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}

export default function GlobalError({ error, unstable_retry }: GlobalErrorProps) {
  useEffect(() => {
    console.error("Error crítico en la web", error.digest ?? error.name);
  }, [error]);

  return (
    <html lang="es">
      <body className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-white">
        <title>Error | TrackFlow</title>
        <main role="alert" className="max-w-xl text-center">
          <h1 className="text-2xl font-bold">TrackFlow no está disponible ahora mismo</h1>
          <p className="mt-3 text-slate-300">
            Se produjo un error inesperado. Vuelve a intentarlo en unos instantes.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <button
              type="button"
              onClick={() => unstable_retry()}
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
        </main>
      </body>
    </html>
  );
}
