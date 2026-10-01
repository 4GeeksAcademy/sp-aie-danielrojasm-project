"use client";

import Link from "next/link";
import { rememberSidebarNavigation } from "@/lib/inventory-telemetry";
import { track } from "@/lib/telemetry";
import { deviceClass } from "@/lib/telemetry-helpers";

interface NavItem {
  /** Clave estable para la telemetría: no cambia si cambia la etiqueta. */
  key: string;
  label: string;
  href: string;
  /** Módulos previstos en próximos hitos: visibles pero deshabilitados. */
  upcoming?: boolean;
}

const navItems: NavItem[] = [
  { key: "dashboard", label: "Panel de operaciones", href: "/" },
  { key: "inventory_stock", label: "Stock por SKU", href: "/inventory/products" },
  { key: "inventory_inbound", label: "Registrar entrada de stock", href: "/inventory/orders/inbound" },
  { key: "inventory_outbound", label: "Registrar salida de stock", href: "/inventory/orders/outbound" },
  { key: "inventory_count", label: "Conteo físico", href: "/inventory/counts" },
  { key: "inventory_history", label: "Historial de movimientos", href: "/inventory/orders" },
  { key: "carriers", label: "Transportistas", href: "/#transportistas" },
  { key: "shipments", label: "Envíos", href: "/#envios" },
  { key: "data_quality", label: "Calidad de datos", href: "/#validaciones" },
  { key: "incidents_board", label: "Panel de incidencias", href: "/incidents" },
  { key: "incidents_new", label: "Registrar incidencia", href: "/incidents/new" },
  { key: "incidents_analyzer", label: "Análisis CSV de incidencias", href: "/incidents/analyzer" },
  { key: "suppliers", label: "Directorio de proveedores", href: "/suppliers" },
  { key: "telemetry_report", label: "Telemetría técnica", href: "/telemetry" },
  { key: "profile", label: "Mi perfil", href: "/account/profile" },
  { key: "returns", label: "Devoluciones", href: "#", upcoming: true },
  { key: "customer_service", label: "Atención al cliente", href: "#", upcoming: true },
  { key: "executive_dashboard", label: "Dashboard ejecutivo", href: "#", upcoming: true },
];

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
