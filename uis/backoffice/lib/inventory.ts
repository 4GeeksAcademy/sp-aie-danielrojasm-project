/**
 * Inventario: tipos, etiquetas y cliente de `/inventory` (TRK-0341).
 *
 * Es el único punto de la UI que habla con la API de inventario: los
 * componentes llaman a estas funciones, nunca a `fetch`. Las peticiones pasan
 * por `requestJson`, que añade `Authorization: Bearer <token>` y convierte
 * cualquier 4xx/5xx en un `ApiError` con un mensaje legible. Next reenvía
 * `/api/inventory/*` a la API (ver `next.config.ts`).
 *
 * Los tipos replican `services/api/schemas.py`; la API es la que valida.
 */
import { requestJson } from "@/lib/api-client";

const INVENTORY_API = "/api/inventory";
const JSON_HEADERS = { "Content-Type": "application/json" };

export type Warehouse = "LA" | "ZGZ";
export type SKUCategory = "fashion" | "electronics" | "cosmetics";
export type ExitType = "dispatch" | "loss";
export type OrderType = "inbound" | "outbound";

/** Fila de `GET /inventory/products` (tabla de stock y selectores). */
export interface SKUListItem {
  id: number;
  name: string;
  sku: string;
  client_name: string;
  category: SKUCategory;
  warehouse: Warehouse;
  /** Entradas − salidas en el almacén del SKU; la API lo calcula, nunca se guarda. */
  current_stock: number;
}

/** Detalle de `GET /inventory/products/{id}`: añade el desglose por almacén. */
export interface SKU extends SKUListItem {
  stock_by_warehouse: Record<Warehouse, number>;
}

/** Movimiento del historial; el SKU llega aplanado. */
export interface InventoryOrder {
  order_type: OrderType;
  id: number;
  sku_code: string;
  sku_name: string;
  client_name: string;
  quantity: number;
  warehouse: Warehouse;
  created_at: string;
  user_uuid: string;
  reference: string | null;
  exit_type: ExitType | null;
  tracking_number: string | null;
}

export interface StockEntryPayload {
  sku_id: number;
  quantity: number;
  reference: string;
  warehouse: Warehouse;
}

export interface StockExitPayload {
  sku_id: number;
  quantity: number;
  exit_type: ExitType;
  tracking_number: string | null;
  warehouse: Warehouse;
}

export interface StockEntry extends StockEntryPayload {
  id: number;
  created_at: string;
  user_uuid: string;
}

export interface StockExit extends StockExitPayload {
  id: number;
  created_at: string;
  user_uuid: string;
}

// ---------------------------------------------------------------------------
// Etiquetas: ningún valor crudo de la API llega a la pantalla.
// ---------------------------------------------------------------------------

export const warehouseLabels: Record<Warehouse, string> = {
  LA: "Los Ángeles (LA)",
  ZGZ: "Zaragoza (ZGZ)",
};

export const skuCategoryLabels: Record<SKUCategory, string> = {
  fashion: "Moda",
  electronics: "Electrónica",
  cosmetics: "Cosmética",
};

export const exitTypeLabels: Record<ExitType, string> = {
  dispatch: "Despacho a cliente",
  loss: "Pérdida confirmada",
};

export const orderTypeLabels: Record<OrderType, string> = {
  inbound: "Entrada de stock",
  outbound: "Salida de stock",
};

// ---------------------------------------------------------------------------
// Nivel de stock
// ---------------------------------------------------------------------------

export type StockLevel = "out" | "low" | "healthy";

/**
 * Umbrales del indicador de stock, por SKU y almacén:
 * - `out`: 0 unidades. No se puede despachar nada.
 * - `low`: de 1 a 49 unidades. Con los volúmenes de las recepciones de las
 *   marcas (40–120 unidades), por debajo de 50 hay que pedir reposición antes
 *   de la siguiente oleada de despachos.
 * - `healthy`: 50 unidades o más.
 */
export const LOW_STOCK_THRESHOLD = 50;

export function getStockLevel(stock: number): StockLevel {
  if (stock <= 0) return "out";
  if (stock < LOW_STOCK_THRESHOLD) return "low";
  return "healthy";
}

export const stockLevelLabels: Record<StockLevel, string> = {
  out: "Sin stock",
  low: "Stock bajo",
  healthy: "Stock saludable",
};

// ---------------------------------------------------------------------------
// Validación en el cliente (guía al usuario; la API aplica la regla real)
// ---------------------------------------------------------------------------

export interface StockEntryFormValues {
  skuId: string;
  quantity: string;
  reference: string;
}

export interface StockExitFormValues {
  skuId: string;
  quantity: string;
  exitType: ExitType;
  trackingNumber: string;
}

export type FormErrors<T> = Partial<Record<keyof T, string>>;

export const REFERENCE_MAX_LENGTH = 100;
export const TRACKING_NUMBER_MAX_LENGTH = 64;

/** Cantidad entera y positiva, o `null` si el texto no lo es. */
export function parseQuantity(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const quantity = Number(trimmed);
  return Number.isSafeInteger(quantity) && quantity > 0 ? quantity : null;
}

const QUANTITY_MESSAGE = "Indica un número entero de unidades mayor que 0.";
const SKU_MESSAGE = "Selecciona el SKU.";

export function validateStockEntry(
  values: StockEntryFormValues,
): FormErrors<StockEntryFormValues> {
  const errors: FormErrors<StockEntryFormValues> = {};
  if (!values.skuId) errors.skuId = SKU_MESSAGE;
  if (parseQuantity(values.quantity) === null) errors.quantity = QUANTITY_MESSAGE;
  const reference = values.reference.trim();
  if (!reference) {
    errors.reference = "Indica la referencia de la marca (p. ej., la orden de compra).";
  } else if (reference.length > REFERENCE_MAX_LENGTH) {
    errors.reference = `La referencia admite hasta ${REFERENCE_MAX_LENGTH} caracteres.`;
  }
  return errors;
}

export function validateStockExit(
  values: StockExitFormValues,
): FormErrors<StockExitFormValues> {
  const errors: FormErrors<StockExitFormValues> = {};
  if (!values.skuId) errors.skuId = SKU_MESSAGE;
  if (parseQuantity(values.quantity) === null) errors.quantity = QUANTITY_MESSAGE;
  // La API exige número de seguimiento en los despachos y lo prohíbe en las pérdidas.
  if (values.exitType === "dispatch") {
    const tracking = values.trackingNumber.trim();
    if (!tracking) {
      errors.trackingNumber = "Un despacho necesita el número de seguimiento del transportista.";
    } else if (tracking.length > TRACKING_NUMBER_MAX_LENGTH) {
      errors.trackingNumber = `El número de seguimiento admite hasta ${TRACKING_NUMBER_MAX_LENGTH} caracteres.`;
    }
  }
  return errors;
}

/** Aviso previo al envío cuando la cantidad supera el stock mostrado. */
export function getOverdraftWarning(quantity: string, available: number | null): string | null {
  const parsed = parseQuantity(quantity);
  if (parsed === null || available === null || parsed <= available) return null;
  return `Solo hay ${available} unidades disponibles en este almacén; estás intentando sacar ${parsed}.`;
}

// ---------------------------------------------------------------------------
// Llamadas a la API
// ---------------------------------------------------------------------------

export function listSKUs(): Promise<SKUListItem[]> {
  return requestJson<SKUListItem[]>(
    `${INVENTORY_API}/products`,
    {},
    "No se pudo cargar el inventario.",
  );
}

export function getSKU(id: number): Promise<SKU> {
  return requestJson<SKU>(
    `${INVENTORY_API}/products/${id}`,
    {},
    "No se pudo consultar el stock del SKU.",
  );
}

export function listInventoryOrders(): Promise<InventoryOrder[]> {
  return requestJson<InventoryOrder[]>(
    `${INVENTORY_API}/orders`,
    {},
    "No se pudo cargar el historial de movimientos.",
  );
}

export function createStockEntry(payload: StockEntryPayload): Promise<StockEntry> {
  return requestJson<StockEntry>(
    `${INVENTORY_API}/orders/inbound`,
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(payload) },
    "No se pudo registrar la entrada de stock.",
  );
}

export function createStockExit(payload: StockExitPayload): Promise<StockExit> {
  return requestJson<StockExit>(
    `${INVENTORY_API}/orders/outbound`,
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(payload) },
    "No se pudo registrar la salida de stock.",
  );
}

// ---------------------------------------------------------------------------
// Formato
// ---------------------------------------------------------------------------

const unitsFormatter = new Intl.NumberFormat("es-ES");
const dateFormatter = new Intl.DateTimeFormat("es-ES", {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatUnits(value: number): string {
  return unitsFormatter.format(value);
}

/** Fecha legible; una fecha inválida no rompe el historial. */
export function formatOrderDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Fecha no disponible" : dateFormatter.format(date);
}

/** Etiqueta para los selectores: código, descripción y almacén. */
export function formatSKUOption(sku: SKUListItem): string {
  return `${sku.sku} · ${sku.name} · ${sku.warehouse}`;
}

/** Lee `?sku=<id>` para preseleccionar el SKU desde la tabla de stock. */
export function parseSkuParam(value: string | string[] | undefined): string {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw && /^\d+$/.test(raw) ? raw : "";
}
