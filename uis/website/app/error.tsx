"use client";

import Link from "next/link";
import { useEffect } from "react";
import { company } from "@/content/site";

interface RouteErrorProps {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}

export default function RouteError({ error, unstable_retry }: RouteErrorProps) {
  useEffect(() => {
    console.error("Error de interfaz en la web", error.digest ?? error.name);
  }, [error]);

  return (
    <section
      role="alert"
      aria-labelledby="route-error-title"
      className="mx-auto max-w-xl px-4 py-24 text-center"
    >
      <h1 id="route-error-title" className="text-2xl font-bold text-white">
        Algo no ha ido bien
      </h1>
      <p className="mt-3 text-slate-300">
        No pudimos mostrar esta página. Vuelve a intentarlo o regresa al inicio.
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
    </section>
  );
}
