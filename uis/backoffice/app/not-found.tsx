import Link from "next/link";

export default function NotFound() {
  return (
    <section
      aria-labelledby="not-found-title"
      className="mx-auto mt-10 max-w-lg rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm"
    >
      <h1 id="not-found-title" className="text-lg font-semibold text-slate-950">
        Esta página no existe
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        Puede que el enlace esté mal escrito o que la sección se haya movido.
      </p>
      <Link
        href="/"
        className="mt-5 inline-flex h-10 items-center rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800"
      >
        Ir al panel de operaciones
      </Link>
    </section>
  );
}
