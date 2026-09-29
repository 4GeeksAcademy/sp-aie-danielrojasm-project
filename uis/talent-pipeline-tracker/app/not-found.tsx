import Link from "next/link";

export default function NotFound() {
  return (
    <section
      aria-labelledby="not-found-title"
      className="mx-auto mt-10 w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-950/90 p-6 text-center text-slate-100"
    >
      <h1 id="not-found-title" className="text-xl font-bold text-white">
        Esta página no existe
      </h1>
      <p className="mt-2 text-sm text-slate-300">
        Puede que el enlace esté mal escrito o que la candidatura se haya eliminado.
      </p>
      <Link
        href="/"
        className="mt-5 inline-flex rounded-lg bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-200"
      >
        Volver al listado
      </Link>
    </section>
  );
}
