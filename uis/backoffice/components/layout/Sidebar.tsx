"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { rememberSidebarNavigation } from "@/lib/inventory-telemetry";
import { findActiveNavKey, navSections, type NavItem } from "@/lib/navigation";
import { track } from "@/lib/telemetry";
import { deviceClass } from "@/lib/telemetry-helpers";

/** Demanda real de cada módulo, incluidos los que aún no existen. */
function trackClick(item: NavItem) {
  if (!item.upcoming) rememberSidebarNavigation(item.href);
  track("sidebar_item_clicked", {
    item_key: item.key,
    is_upcoming: Boolean(item.upcoming),
    device_class: deviceClass(),
  });
}

export function Sidebar() {
  const activeKey = findActiveNavKey(usePathname());
  const navRef = useRef<HTMLElement>(null);

  // En móvil el menú es una tira horizontal: sin esto, el módulo activo queda fuera de la vista.
  useEffect(() => {
    navRef.current
      ?.querySelector('[aria-current="page"]')
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeKey]);

  return (
    <aside className="border-b border-slate-800 bg-slate-900 text-slate-200 lg:sticky lg:top-0 lg:h-screen lg:w-64 lg:shrink-0 lg:overflow-y-auto lg:border-b-0 lg:border-r">
      <Link href="/" className="flex items-center gap-3 px-5 py-5">
        <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-cyan-300 text-sm font-black text-slate-950">
          TF
        </span>
        <span>
          <span className="block text-sm font-bold text-white">
            TrackFlow Tech
          </span>
          <span className="block text-xs text-slate-400">Backoffice interno</span>
        </span>
      </Link>
      <nav ref={navRef} aria-label="Módulos del backoffice" className="px-3 pb-4">
        {/* En móvil las secciones forman una sola tira horizontal; en escritorio, una columna con títulos. */}
        <div className="flex gap-1 overflow-x-auto lg:flex-col lg:gap-4">
          {navSections.map((section) => (
            <div key={section.key} role="group" aria-labelledby={`nav-${section.key}`}>
              <p
                id={`nav-${section.key}`}
                className="sr-only px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500 lg:not-sr-only lg:block"
              >
                {section.title}
              </p>
              <ul className="flex gap-1 lg:flex-col">
                {section.items.map((item) =>
                  item.upcoming ? (
                    <li key={item.key}>
                      {/* Botón sin acción: el clic solo registra la demanda del módulo. */}
                      <button
                        type="button"
                        aria-disabled="true"
                        onClick={() => trackClick(item)}
                        className="flex w-full cursor-not-allowed items-center justify-between gap-2 whitespace-nowrap rounded-md px-3 py-2 text-left text-sm text-slate-500"
                      >
                        {item.label}
                        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                          Próximo
                        </span>
                      </button>
                    </li>
                  ) : (
                    <li key={item.key}>
                      <Link
                        href={item.href}
                        onClick={() => trackClick(item)}
                        aria-current={item.key === activeKey ? "page" : undefined}
                        className={`block whitespace-nowrap rounded-md px-3 py-2 text-sm hover:bg-slate-800 hover:text-white ${
                          item.key === activeKey ? "bg-slate-800 font-semibold text-white" : ""
                        }`}
                      >
                        {item.label}
                      </Link>
                    </li>
                  ),
                )}
              </ul>
            </div>
          ))}
        </div>
      </nav>
    </aside>
  );
}
