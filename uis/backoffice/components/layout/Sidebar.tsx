import Link from "next/link";

interface NavItem {
  label: string;
  href: string;
  /** Módulos previstos en próximos hitos: visibles pero deshabilitados. */
  upcoming?: boolean;
}

const navItems: NavItem[] = [
  { label: "Panel de operaciones", href: "/" },
  { label: "Inventario", href: "/#inventario" },
  { label: "Transportistas", href: "/#transportistas" },
  { label: "Envíos", href: "/#envios" },
  { label: "Calidad de datos", href: "/#validaciones" },
  { label: "Análisis de incidencias", href: "/incidents" },
  { label: "Directorio de proveedores", href: "/suppliers" },
  { label: "Devoluciones", href: "#", upcoming: true },
  { label: "Atención al cliente", href: "#", upcoming: true },
  { label: "Dashboard ejecutivo", href: "#", upcoming: true },
];

export function Sidebar() {
  return (
    <aside className="border-b border-slate-800 bg-slate-900 text-slate-200 lg:sticky lg:top-0 lg:h-screen lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r">
      <div className="flex items-center gap-3 px-5 py-5">
        <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-cyan-300 text-sm font-black text-slate-950">
          TF
        </span>
        <span>
          <span className="block text-sm font-bold text-white">
            TrackFlow Tech
          </span>
          <span className="block text-xs text-slate-400">Backoffice interno</span>
        </span>
      </div>
      <nav aria-label="Módulos del backoffice" className="px-3 pb-4">
        <ul className="flex gap-1 overflow-x-auto lg:flex-col">
          {navItems.map((item) =>
            item.upcoming ? (
              <li key={item.label}>
                <span
                  className="flex items-center justify-between gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm text-slate-500"
                  aria-disabled="true"
                >
                  {item.label}
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                    Próximo
                  </span>
                </span>
              </li>
            ) : (
              <li key={item.label}>
                <Link
                  href={item.href}
                  className="block whitespace-nowrap rounded-md px-3 py-2 text-sm hover:bg-slate-800 hover:text-white"
                >
                  {item.label}
                </Link>
              </li>
            ),
          )}
        </ul>
      </nav>
    </aside>
  );
}
