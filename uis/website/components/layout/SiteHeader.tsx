import Link from "next/link";
import { Logo } from "@/components/ui/Logo";
import { APPLICATION_PATH, company, navLinks } from "@/content/site";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-cyan-300/20 bg-slate-950/85 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
        <Logo subtitle={company.tagline} />

        <nav aria-label="Navegación principal">
          <ul className="flex flex-wrap items-center gap-1 text-sm font-medium sm:gap-4">
            {navLinks.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  className="rounded px-3 py-2 text-slate-200 hover:bg-slate-800"
                >
                  {link.label}
                </Link>
              </li>
            ))}
            <li>
              <Link
                href={APPLICATION_PATH}
                className="rounded bg-cyan-300 px-4 py-2 font-semibold text-slate-950 hover:bg-cyan-200"
              >
                Aplicar
              </Link>
            </li>
          </ul>
        </nav>
      </div>
    </header>
  );
}
