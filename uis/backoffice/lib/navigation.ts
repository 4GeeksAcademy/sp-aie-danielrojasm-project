/**
 * Mapa de navegación del backoffice: única fuente para el sidebar y el
 * directorio de módulos del panel de inicio.
 */

export interface NavItem {
  /** Clave estable para la telemetría: no cambia si cambia la etiqueta. */
  key: string;
  label: string;
  href: string;
  /** Módulos previstos en próximos hitos: visibles pero deshabilitados. */
  upcoming?: boolean;
  /** Rutas hijas sin entrada propia que se marcan con este ítem (p. ej. `/account`). */
  matchPrefixes?: string[];
}

export interface NavSection {
  key: string;
  title: string;
  /** Resumen del área para la tarjeta del panel de inicio. */
  description: string;
  items: NavItem[];
}

/** Rutas accesibles sin sesión: se muestran sin sidebar ni barra superior. */
export const PUBLIC_ROUTES = new Set(["/login", "/register", "/forgot-password", "/reset-password"]);

export const navSections: NavSection[] = [
  {
    key: "operations",
    title: "Operaciones",
    description: "KPIs de almacén, selección de transportista, envíos y desempeño semanal.",
    items: [
      { key: "dashboard", label: "Panel de operaciones", href: "/" },
      { key: "weekly_performance_report", label: "Reporte semanal de desempeño", href: "/reporting" },
      { key: "carriers", label: "Transportistas", href: "/#transportistas" },
      { key: "shipments", label: "Envíos", href: "/#envios" },
      { key: "data_quality", label: "Calidad de datos", href: "/#validaciones" },
    ],
  },
  {
    key: "inventory",
    title: "Inventario",
    description: "Stock por SKU y almacén, movimientos de entrada y salida y conteos físicos.",
    items: [
      { key: "inventory_stock", label: "Stock por SKU", href: "/inventory/products", matchPrefixes: ["/inventory"] },
      { key: "inventory_inbound", label: "Registrar entrada de stock", href: "/inventory/orders/inbound" },
      { key: "inventory_outbound", label: "Registrar salida de stock", href: "/inventory/orders/outbound" },
      { key: "inventory_count", label: "Conteo físico", href: "/inventory/counts" },
      { key: "inventory_history", label: "Historial de movimientos", href: "/inventory/orders" },
    ],
  },
  {
    key: "incidents",
    title: "Incidencias",
    description: "Registro, seguimiento y análisis por lotes de las incidencias operativas.",
    items: [
      { key: "incidents_board", label: "Panel de incidencias", href: "/incidents" },
      { key: "incidents_new", label: "Registrar incidencia", href: "/incidents/new" },
      { key: "incidents_analyzer", label: "Análisis CSV de incidencias", href: "/incidents/analyzer" },
    ],
  },
  {
    key: "commercial",
    title: "Comercial y proveedores",
    description: "Proveedores, base de conocimiento comercial y respuesta a RFPs.",
    items: [
      { key: "suppliers", label: "Directorio de proveedores", href: "/suppliers" },
      { key: "knowledge_assistant", label: "Asistente comercial", href: "/knowledge" },
      { key: "rfp_intake", label: "Recepción de RFPs", href: "/rfps" },
    ],
  },
  {
    key: "customer_experience",
    title: "Experiencia de cliente",
    description: "Chat con el agente de primera línea para las consultas de clientes.",
    items: [{ key: "customer_service", label: "Atención al cliente", href: "/atencion-cliente" }],
  },
  {
    key: "technology",
    title: "Tecnología",
    description: "Telemetría técnica del backoffice y de la API.",
    items: [{ key: "telemetry_report", label: "Telemetría técnica", href: "/telemetry" }],
  },
  {
    key: "account",
    title: "Cuenta",
    description: "Datos personales y cambio de contraseña.",
    items: [{ key: "profile", label: "Mi perfil", href: "/account/profile", matchPrefixes: ["/account"] }],
  },
  {
    key: "upcoming",
    title: "Próximamente",
    description: "Módulos previstos en próximos hitos.",
    items: [
      { key: "returns", label: "Devoluciones", href: "#", upcoming: true },
      { key: "executive_dashboard", label: "Dashboard ejecutivo", href: "#", upcoming: true },
    ],
  },
];

function matchLength(pathname: string, prefix: string): number {
  if (prefix === "/") return pathname === "/" ? 1 : 0;
  return pathname === prefix || pathname.startsWith(`${prefix}/`) ? prefix.length : 0;
}

/**
 * Ítem del menú que corresponde a la ruta actual: gana el prefijo más largo,
 * así `/inventory/orders/inbound` marca la entrada y no el historial. Las anclas
 * del panel (`/#envios`) nunca se marcan; la ruta `/` marca el panel.
 */
export function findActiveNavKey(pathname: string): string | null {
  let best: { key: string; length: number } | null = null;
  for (const item of navSections.flatMap((section) => section.items)) {
    if (item.upcoming || item.href.includes("#")) continue;
    for (const prefix of [item.href, ...(item.matchPrefixes ?? [])]) {
      const length = matchLength(pathname, prefix);
      if (length > 0 && (best === null || length > best.length)) best = { key: item.key, length };
    }
  }
  return best?.key ?? null;
}
