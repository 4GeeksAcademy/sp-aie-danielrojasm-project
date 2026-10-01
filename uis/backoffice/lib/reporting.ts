/**
 * Reporte Semanal de Desempeño por Almacén y Cliente: tipos, etiquetas y cliente
 * de `GET /reporting/weekly-warehouse-client-performance` y `GET /reporting/pipeline-runs/latest`.
 *
 * Único punto de la UI que llama a `services/reporting/`. Pasa por `requestJson`
 * (Bearer y 401 → `/login`) y por el rewrite `/api/reporting/*`. Los tipos
 * replican `services/reporting/models.py`. Es una vista de negocio para Thomas
 * (CEO) y Ana (Operaciones de almacén): los nombres de KPI son los de
 * `CONTEXT-company.md` y las semanas son semanas ISO (lunes a domingo, UTC).
 */
import { ApiError, requestJson } from "@/lib/api-client";

const REPORTING_API = "/api/reporting";

export type ReportingWarehouse = "los_angeles" | "zaragoza";
export type ReconciliationStatus = "ok" | "gap" | "unavailable";
export type PipelineRunStatus = "pending" | "running" | "completed" | "failed" | "crashed" | "cancelled";

export interface WeeklyPerformanceEntry {
  warehouse: ReportingWarehouse;
  client_id: string;
  inbound_units_count: number;
  outbound_orders_count: number;
  stockout_events_count: number;
  discrepancy_events_count: number;
  discrepancy_rate: number;
}

export interface WeeklyPerformanceReport {
  week_start: string;
  computed_at: string | null;
  run_id: string | null;
  reconciliation_status: ReconciliationStatus | null;
  entries: WeeklyPerformanceEntry[];
}

export interface PipelineRun {
  run_id: string;
  status: PipelineRunStatus;
  started_at: string;
  finished_at: string | null;
  last_completed_at: string | null;
  stale: boolean;
}

/** Los cuatro KPIs de la sección «KPIs a medir» de `CONTEXT-company.md`. */
export type WeeklyKpi = "inbound_volume" | "outbound_throughput" | "stockout_frequency" | "discrepancy_rate";

export interface KpiDefinition {
  /** Nombre exacto del KPI en `CONTEXT-company.md`. */
  label: string;
  /** Qué mide, en palabras del negocio. */
  question: string;
  /** Unidad tras el número (p. ej. «unidades»); vacía para la tasa. */
  unit: string;
}

export const weeklyKpis: Record<WeeklyKpi, KpiDefinition> = {
  inbound_volume: {
    label: "Volumen de entrada",
    question: "Unidades de mercancía del cliente que recibió el almacén durante la semana.",
    unit: "unidades",
  },
  outbound_throughput: {
    label: "Throughput de salida",
    question: "Pedidos que el almacén preparó y despachó para el cliente durante la semana.",
    unit: "pedidos",
  },
  stockout_frequency: {
    label: "Frecuencia de quiebre de stock",
    question: "Veces que un producto del cliente cayó por debajo del mínimo configurado en ese almacén.",
    unit: "veces",
  },
  discrepancy_rate: {
    label: "Tasa de discrepancia",
    question: "Discrepancias de inventario detectadas por cada pedido despachado. Cuanto más alta, más urgente auditar.",
    unit: "",
  },
};

export const KPI_ORDER: WeeklyKpi[] = ["inbound_volume", "outbound_throughput", "stockout_frequency", "discrepancy_rate"];

export const reportingWarehouseLabels: Record<ReportingWarehouse, string> = {
  los_angeles: "Los Ángeles",
  zaragoza: "Zaragoza",
};

export const pipelineRunStatusLabels: Record<PipelineRunStatus, string> = {
  pending: "en cola",
  running: "actualizándose ahora",
  completed: "completada",
  failed: "fallida",
  crashed: "interrumpida",
  cancelled: "cancelada",
};

/** `null` si la semana (o ninguna) se ha calculado todavía: es un estado vacío, no un error. */
export async function getWeeklyPerformance(weekStart: string): Promise<WeeklyPerformanceReport | null> {
  const query = weekStart ? `?${new URLSearchParams({ week_start: weekStart })}` : "";
  try {
    return await requestJson<WeeklyPerformanceReport>(
      `${REPORTING_API}/weekly-warehouse-client-performance${query}`,
      {},
      "No se pudo cargar el reporte semanal.",
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** `null` si el pipeline nunca ha corrido. */
export async function getLatestPipelineRun(): Promise<PipelineRun | null> {
  try {
    return await requestJson<PipelineRun>(
      `${REPORTING_API}/pipeline-runs/latest`,
      {},
      "No se pudo consultar la última actualización del reporte.",
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Valor de un KPI en una fila del reporte. */
export function kpiValue(entry: WeeklyPerformanceEntry, kpi: WeeklyKpi): number {
  switch (kpi) {
    case "inbound_volume":
      return entry.inbound_units_count;
    case "outbound_throughput":
      return entry.outbound_orders_count;
    case "stockout_frequency":
      return entry.stockout_events_count;
    case "discrepancy_rate":
      return entry.discrepancy_rate;
  }
}

/** Totales de la semana; la tasa se recalcula sobre los totales (no es la media de las tasas). */
export function weeklyTotals(entries: WeeklyPerformanceEntry[]): Record<WeeklyKpi, number> {
  const sum = (pick: (entry: WeeklyPerformanceEntry) => number) =>
    entries.reduce((total, entry) => total + pick(entry), 0);
  const orders = sum((entry) => entry.outbound_orders_count);
  const discrepancies = sum((entry) => entry.discrepancy_events_count);
  return {
    inbound_volume: sum((entry) => entry.inbound_units_count),
    outbound_throughput: orders,
    stockout_frequency: sum((entry) => entry.stockout_events_count),
    discrepancy_rate: orders > 0 ? discrepancies / orders : 0,
  };
}

// `always`: es-ES no agrupa los números de 4 cifras y «2708» se lee peor que «2.708».
const integerFormatter = new Intl.NumberFormat("es-ES", { useGrouping: "always" });

export function formatKpi(kpi: WeeklyKpi, value: number): string {
  if (kpi === "discrepancy_rate") {
    return `${(value * 100).toLocaleString("es-ES", { maximumFractionDigits: 1 })} %`;
  }
  return integerFormatter.format(value);
}

/** `purestep-footwear` → «Purestep Footwear»: el identificador del cliente, legible. */
export function clientName(clientId: string): string {
  return clientId
    .split("-")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function parseDay(day: string): Date {
  return new Date(`${day}T00:00:00Z`);
}

/** Lunes de la semana desplazado `weeks` semanas (`AAAA-MM-DD`). */
export function shiftWeek(weekStart: string, weeks: number): string {
  const date = parseDay(weekStart);
  date.setUTCDate(date.getUTCDate() + weeks * 7);
  return date.toISOString().slice(0, 10);
}

const dayMonthYear = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const dayMonth = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "long", timeZone: "UTC" });
const dayOnly = new Intl.DateTimeFormat("es-ES", { day: "numeric", timeZone: "UTC" });

/** «del 21 al 27 de septiembre de 2026» (lunes a domingo). */
export function formatWeekRange(weekStart: string): string {
  const monday = parseDay(weekStart);
  const sunday = parseDay(shiftWeek(weekStart, 1));
  sunday.setUTCDate(sunday.getUTCDate() - 1);
  const sameMonth = monday.getUTCMonth() === sunday.getUTCMonth();
  const sameYear = monday.getUTCFullYear() === sunday.getUTCFullYear();
  const from = sameMonth ? dayOnly.format(monday) : sameYear ? dayMonth.format(monday) : dayMonthYear.format(monday);
  return `del ${from} al ${dayMonthYear.format(sunday)}`;
}

const dateTimeFormatter = new Intl.DateTimeFormat("es-ES", { dateStyle: "long", timeStyle: "short", timeZone: "UTC" });

export function formatUpdatedAt(value: string): string {
  return `${dateTimeFormatter.format(new Date(value))} (UTC)`;
}
