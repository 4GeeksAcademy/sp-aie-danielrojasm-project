/**
 * Telemetría del inventario en el navegador: identificadores de negocio con el
 * vocabulario del plan y estado de los formularios de movimientos.
 *
 * Los eventos obligatorios (órdenes creadas, umbral, rechazos, descuadres) no
 * se emiten aquí: los emite la API tras el commit. El navegador solo aporta
 * contexto de UX (inicio y abandono de formularios, avisos, validación).
 */
import type { SKUListItem, Warehouse } from "@/lib/inventory";
import type {
  BackofficeEventProperties,
  InventoryForm,
  InventoryIdentity,
  TelemetryWarehouse,
} from "@/lib/telemetry-events";

const TELEMETRY_WAREHOUSES: Record<Warehouse, TelemetryWarehouse> = {
  LA: "los_angeles",
  ZGZ: "zaragoza",
};
const WAREHOUSE_COUNTRIES = { LA: "US", ZGZ: "ES" } as const;

export function telemetryWarehouse(warehouse: Warehouse): TelemetryWarehouse {
  return TELEMETRY_WAREHOUSES[warehouse];
}

/**
 * Slug de la marca igual que la API (`services/api/inventory_telemetry.py`):
 * `PureStep Footwear` → `purestep-footwear`. Un test fija los mismos casos.
 */
export function clientId(clientName: string): string {
  const ascii = clientName.normalize("NFKD").replace(/[^\x00-\x7F]/g, "");
  const slug = ascii.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return slug || "unknown";
}

export function inventoryIdentity(sku: SKUListItem): InventoryIdentity {
  return {
    warehouse: TELEMETRY_WAREHOUSES[sku.warehouse],
    country: WAREHOUSE_COUNTRIES[sku.warehouse],
    client_id: clientId(sku.client_name),
    product_id: sku.sku,
    product_category: sku.category,
  };
}

// ---------------------------------------------------------------------------
// Validación en el cliente
// ---------------------------------------------------------------------------

/** Nombre del campo en la API para cada campo del formulario. */
const API_FIELD_NAMES: Record<string, string> = {
  skuId: "sku_id",
  quantity: "quantity",
  reference: "reference",
  exitType: "exit_type",
  trackingNumber: "tracking_number",
};

type ValidationFailure = BackofficeEventProperties["inventory_validation_failed"];

/**
 * `inventory_validation_failed` de la capa cliente: nombres de campo y tipo de
 * error (`missing` si estaba vacío, `value_error` si no), nunca el valor.
 */
export function clientValidationFailure(
  operation: ValidationFailure["operation"],
  values: Record<string, string>,
  errors: Partial<Record<string, string>>,
  sku: SKUListItem | null,
): ValidationFailure {
  const fields = Object.keys(errors).filter((field) => errors[field]);
  return {
    layer: "client",
    operation,
    product_id: sku?.sku ?? null,
    warehouse: sku ? TELEMETRY_WAREHOUSES[sku.warehouse] : null,
    client_id: sku ? clientId(sku.client_name) : null,
    error_fields: fields.map((field) => API_FIELD_NAMES[field] ?? field).slice(0, 10),
    error_types: fields.map((field) => (values[field]?.trim() ? "value_error" : "missing")).slice(0, 10),
    error_count: fields.length,
  };
}

// ---------------------------------------------------------------------------
// Formularios de movimientos en curso
// ---------------------------------------------------------------------------

export type AbandonReason = BackofficeEventProperties["inventory_form_abandoned"]["exit_reason"];

interface ActiveForm {
  form: InventoryForm;
  abandon: (reason: AbandonReason) => void;
}

let activeForm: ActiveForm | null = null;

/** El formulario empezado y sin enviar de esta pestaña (como mucho uno). */
export function registerActiveInventoryForm(form: ActiveForm | null): void {
  activeForm = form;
}

export function isActiveInventoryForm(form: ActiveForm): boolean {
  return activeForm === form;
}

export function hasUnsavedInventoryForm(): boolean {
  return activeForm !== null;
}

/** La sesión caducó: el formulario abierto se pierde con la redirección al login. */
export function abandonActiveInventoryForm(reason: AbandonReason): void {
  activeForm?.abandon(reason);
}

// ---------------------------------------------------------------------------
// Punto de entrada de los formularios
// ---------------------------------------------------------------------------

/** Una navegación desde el menú lateral cuenta como origen durante unos segundos. */
const SIDEBAR_NAVIGATION_TTL_MS = 10_000;
let sidebarNavigation: { href: string; at: number } | null = null;

export function rememberSidebarNavigation(href: string): void {
  sidebarNavigation = { href, at: Date.now() };
}

export function inventoryEntryPoint(
  path: string,
  prefilledSku: boolean,
): BackofficeEventProperties["inventory_form_started"]["entry_point"] {
  if (prefilledSku) return "stock_table_row";
  const fromSidebar =
    sidebarNavigation !== null &&
    sidebarNavigation.href === path &&
    Date.now() - sidebarNavigation.at < SIDEBAR_NAVIGATION_TTL_MS;
  return fromSidebar ? "sidebar" : "direct_url";
}
