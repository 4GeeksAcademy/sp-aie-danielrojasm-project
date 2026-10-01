/**
 * Reporte técnico de telemetría: tipos, etiquetas y cliente de `GET /telemetry/report`.
 *
 * Único punto de la UI que llama al reporte. Pasa por `requestJson` (Bearer y
 * 401 → `/login`) y por el rewrite `/api/telemetry/*`. Los tipos replican
 * `services/api/telemetry_report_models.py`; los días (`date`) están en UTC y
 * las tasas van de 0 a 1. Es una vista de ingeniería, sin métricas de negocio.
 */
import { requestJson } from "@/lib/api-client";

const REPORT_API = "/api/telemetry/report";

export type EventService = "backoffice" | "api" | "job";
export type ErrorKind = "system" | "rejected";

export interface EventsPerDayRow {
  date: string;
  service: EventService;
  events: number;
  sessions: number;
}

export interface EventsByTypeRow {
  event_type: string;
  events: number;
  active_days: number;
  last_seen: string;
  share: number;
}

export interface ErrorRateRow {
  date: string;
  event_type: string;
  error_kind: ErrorKind;
  errors: number;
  total_events: number;
  error_rate: number;
}

export interface PageLoadRow {
  date: string;
  route: string;
  samples: number;
  ttfb_ms_p75: number | null;
  fcp_ms_p75: number | null;
  lcp_ms_p75: number | null;
  inp_ms_p75: number | null;
  cls_p75: number | null;
}

export interface AuthFailureRateRow {
  date: string;
  attempts: number;
  failed: number;
  succeeded: number;
  failure_rate: number;
}

export interface TelemetryReport {
  period: { from: string; to: string };
  generated_at: string;
  metrics: {
    events_per_day: EventsPerDayRow[];
    events_by_type: EventsByTypeRow[];
    error_rate_by_type: ErrorRateRow[];
    page_load_by_route: PageLoadRow[];
    auth_failure_rate: AuthFailureRateRow[];
  };
}

/** Días elegidos en la UI (`AAAA-MM-DD`, ambos incluidos); vacíos = últimos 7 días. */
export interface ReportRange {
  from: string;
  to: string;
}

export const serviceLabels: Record<EventService, string> = {
  backoffice: "Backoffice",
  api: "API",
  job: "Procesos",
};

export const errorKindLabels: Record<ErrorKind, string> = {
  system: "Fallo del sistema",
  rejected: "Petición rechazada",
};

function nextDay(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/** Query de la API: el día final se incluye entero porque `end_date` es exclusivo. */
export function reportQuery({ from, to }: ReportRange): string {
  const params = new URLSearchParams();
  if (from) params.set("start_date", `${from}T00:00:00Z`);
  if (to) params.set("end_date", `${nextDay(to)}T00:00:00Z`);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function getTelemetryReport(range: ReportRange): Promise<TelemetryReport> {
  return requestJson<TelemetryReport>(
    `${REPORT_API}${reportQuery(range)}`,
    {},
    "No se pudo cargar el reporte de telemetría.",
  );
}

const utcFormatter = new Intl.DateTimeFormat("es-ES", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

export function formatUtc(value: string): string {
  return `${utcFormatter.format(new Date(value))} UTC`;
}

export function formatRate(rate: number): string {
  return `${(rate * 100).toLocaleString("es-ES", { maximumFractionDigits: 1 })} %`;
}

type VitalName = "ttfb_ms_p75" | "fcp_ms_p75" | "lcp_ms_p75" | "inp_ms_p75" | "cls_p75";
export type VitalRating = "good" | "needs_improvement" | "poor";

/** Umbrales oficiales de Web Vitals: [bueno hasta, mejorable hasta]. */
const VITAL_THRESHOLDS: Record<VitalName, [number, number]> = {
  ttfb_ms_p75: [800, 1800],
  fcp_ms_p75: [1800, 3000],
  lcp_ms_p75: [2500, 4000],
  inp_ms_p75: [200, 500],
  cls_p75: [0.1, 0.25],
};

export function rateVital(name: VitalName, value: number): VitalRating {
  const [good, needsImprovement] = VITAL_THRESHOLDS[name];
  if (value <= good) return "good";
  return value <= needsImprovement ? "needs_improvement" : "poor";
}
