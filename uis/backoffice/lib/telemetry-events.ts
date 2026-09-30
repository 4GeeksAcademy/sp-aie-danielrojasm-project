/**
 * Catálogo de eventos que emite el backoffice (`docs/telemetry/telemetry-plan.md`).
 *
 * Son los eventos del plan cuyo emisor es `backoffice`. Los obligatorios de
 * inventario no están aquí a propósito: los emite la API desde la transacción
 * del movimiento, y un evento del navegador nunca los sustituye.
 *
 * Cada interfaz es el allowlist de `properties` de su evento: `track()` no
 * compila con una clave de más, y en ejecución descarta cualquier clave que no
 * esté en `EVENT_ALLOWLISTS`. Un test compara este archivo con
 * `docs/telemetry/event-schemas.json`.
 */

/** Versión de los esquemas del plan; todos los eventos empiezan en 1.0.0. */
export const TELEMETRY_SCHEMA_VERSION = "1.0.0";

export type TelemetryWarehouse = "los_angeles" | "zaragoza";
export type TelemetryCountry = "US" | "ES";
export type TelemetryCategory = "fashion" | "electronics" | "cosmetics";
export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type DeviceClass = "mobile" | "desktop";
export type BackofficeSection = "dashboard" | "inventory" | "incidents" | "suppliers" | "account" | "auth";
export type InventoryForm = "inbound_order" | "outbound_order";
export type InventoryFormField =
  | "sku_id"
  | "quantity"
  | "reference"
  | "warehouse"
  | "exit_type"
  | "tracking_number";

/** Campos mínimos de todo evento de inventario (sin `quantity`, que depende del evento). */
export interface InventoryIdentity {
  warehouse: TelemetryWarehouse;
  country: TelemetryCountry;
  client_id: string;
  product_id: string;
  product_category: TelemetryCategory;
}

export interface BackofficeEventProperties {
  inventory_validation_failed: {
    layer: "client";
    operation: "product_create" | "inbound_order" | "outbound_order";
    product_id: string | null;
    warehouse: TelemetryWarehouse | null;
    client_id: string | null;
    error_fields: string[];
    error_types: string[];
    error_count: number;
  };
  inventory_form_started: {
    form: InventoryForm;
    entry_point: "sidebar" | "stock_table_row" | "direct_url";
    prefilled_sku: boolean;
  };
  inventory_form_abandoned: {
    form: InventoryForm;
    duration_ms: number;
    last_field: InventoryFormField | null;
    fields_completed: number;
    had_validation_error: boolean;
    had_server_error: boolean;
    exit_reason: "navigation" | "page_hidden" | "session_expired";
  };
  stock_overdraft_warning_displayed: InventoryIdentity & {
    quantity: number;
    available_quantity: number;
  };
  session_expired: {
    cause: "token_expired" | "token_invalid";
    route: string;
    session_age_s: number;
    had_unsaved_form: boolean;
  };
  session_closed: {
    session_duration_s: number;
  };
  page_load_recorded: {
    route: string;
    ttfb_ms: number | null;
    fcp_ms: number | null;
    lcp_ms: number | null;
    inp_ms: number | null;
    cls: number | null;
    navigation_type: "navigate" | "reload" | "back_forward" | "prerender";
    device_class: DeviceClass;
  };
  api_call_failed: {
    api_route: string;
    http_method: HttpMethod;
    status_code: number;
    failure_type: "network" | "server_error" | "invalid_response";
    page_route: string;
    suppressed_count: number;
  };
  frontend_error_captured: {
    boundary: "route" | "global" | "window" | "unhandled_rejection";
    page_route: string;
    error_name: string;
    error_digest: string | null;
    fingerprint: string;
    suppressed_count: number;
  };
  error_retry_attempted: {
    component: "retry_alert" | "error_fallback";
    page_route: string;
    attempt: number;
    outcome: "success" | "failure";
  };
  inventory_filter_applied: {
    view: "stock_table";
    warehouse: TelemetryWarehouse | "all";
    result_count: number;
  };
  page_viewed: {
    route: string;
    section: BackofficeSection;
    previous_route: string | null;
  };
  sidebar_item_clicked: {
    item_key: string;
    is_upcoming: boolean;
    device_class: DeviceClass;
  };
}

export type BackofficeEventType = keyof BackofficeEventProperties;

type Allowlists = { [T in BackofficeEventType]: readonly (keyof BackofficeEventProperties[T])[] };

/** Allowlist de ejecución: lo que no esté aquí no sale del navegador. */
export const EVENT_ALLOWLISTS: Allowlists = {
  inventory_validation_failed: [
    "layer",
    "operation",
    "product_id",
    "warehouse",
    "client_id",
    "error_fields",
    "error_types",
    "error_count",
  ],
  inventory_form_started: ["form", "entry_point", "prefilled_sku"],
  inventory_form_abandoned: [
    "form",
    "duration_ms",
    "last_field",
    "fields_completed",
    "had_validation_error",
    "had_server_error",
    "exit_reason",
  ],
  stock_overdraft_warning_displayed: [
    "warehouse",
    "country",
    "client_id",
    "product_id",
    "product_category",
    "quantity",
    "available_quantity",
  ],
  session_expired: ["cause", "route", "session_age_s", "had_unsaved_form"],
  session_closed: ["session_duration_s"],
  page_load_recorded: [
    "route",
    "ttfb_ms",
    "fcp_ms",
    "lcp_ms",
    "inp_ms",
    "cls",
    "navigation_type",
    "device_class",
  ],
  api_call_failed: [
    "api_route",
    "http_method",
    "status_code",
    "failure_type",
    "page_route",
    "suppressed_count",
  ],
  frontend_error_captured: [
    "boundary",
    "page_route",
    "error_name",
    "error_digest",
    "fingerprint",
    "suppressed_count",
  ],
  error_retry_attempted: ["component", "page_route", "attempt", "outcome"],
  inventory_filter_applied: ["view", "warehouse", "result_count"],
  page_viewed: ["route", "section", "previous_route"],
  sidebar_item_clicked: ["item_key", "is_upcoming", "device_class"],
};
