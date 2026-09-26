import { company } from "@/content/site";

export function SiteFooter() {
  return (
    <footer className="border-t border-slate-800 bg-slate-950">
      <div className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-10 sm:px-6 md:grid-cols-3 lg:px-8">
        <div>
          <h2 className="text-lg font-bold text-white">{company.name}</h2>
          <p className="mt-3 text-sm text-slate-400">
            Logística de última milla y gestión de almacenes para marcas de
            e-commerce.
          </p>
        </div>
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.15em] text-cyan-200">
            Contacto
          </h2>
          <p className="mt-3 text-sm text-slate-300">
            <a href={`tel:${company.phone}`} className="hover:text-cyan-100">
              {company.phoneDisplay}
            </a>
          </p>
          <p className="text-sm text-slate-300">
            <a href={`mailto:${company.email}`} className="hover:text-cyan-100">
              {company.email}
            </a>
          </p>
        </div>
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.15em] text-cyan-200">
            Sedes
          </h2>
          <ul className="mt-3 space-y-1 text-sm text-slate-300">
            {company.offices.map((office) => (
              <li key={office.city}>
                {office.city}, {office.region} ({office.country})
              </li>
            ))}
          </ul>
        </div>
      </div>
      <p className="border-t border-slate-900 py-4 text-center text-xs text-slate-500">
        © {new Date().getFullYear()} {company.name}. Fundada en{" "}
        {company.foundingYear}.
      </p>
    </footer>
  );
}
