import Link from "next/link";
import { Panel } from "@/components/ui/Panel";
import { navSections } from "@/lib/navigation";

/** Tarjetas del panel de inicio con los mismos accesos que el sidebar. */
export function ModuleDirectory() {
  // El propio panel ya es la página actual: no se enlaza a sí mismo.
  const sections = navSections.map((section) => ({
    ...section,
    items: section.items.filter((item) => item.href !== "/"),
  }));

  return (
    <Panel
      id="modulos"
      title="Módulos del backoffice"
      description="Accesos directos a cada área. El menú lateral tiene los mismos enlaces."
    >
      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {sections.map((section) => (
          <li key={section.key} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-sm font-semibold text-slate-900">{section.title}</h3>
            <p className="mt-1 text-xs text-slate-500">{section.description}</p>
            <ul className="mt-3 space-y-1.5 text-sm">
              {section.items.map((item) => (
                <li key={item.key}>
                  {item.upcoming ? (
                    <span className="flex items-center gap-2 text-slate-400">
                      {item.label}
                      <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                        Próximo
                      </span>
                    </span>
                  ) : (
                    <Link href={item.href} className="font-medium text-cyan-800 hover:underline">
                      {item.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
