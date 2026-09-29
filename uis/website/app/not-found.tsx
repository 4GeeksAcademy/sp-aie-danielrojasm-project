import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Página no encontrada" };

export default function NotFound() {
  return (
    <section aria-labelledby="not-found-title" className="mx-auto max-w-xl px-4 py-24 text-center">
      <h1 id="not-found-title" className="text-2xl font-bold text-white">
        No encontramos esta página
      </h1>
      <p className="mt-3 text-slate-300">
        Puede que el enlace esté mal escrito o que la página ya no exista.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link
          href="/"
          className="rounded-md bg-cyan-300 px-5 py-2.5 font-semibold text-slate-950 hover:bg-cyan-200"
        >
          Ir al inicio
        </Link>
        <Link
          href="/#contacto"
          className="rounded-md border border-slate-600 px-5 py-2.5 font-semibold text-white hover:border-cyan-300"
        >
          Contactar con TrackFlow
        </Link>
      </div>
    </section>
  );
}
