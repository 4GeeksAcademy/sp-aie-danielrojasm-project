/**
 * Recepción de RFPs en modo ticket: cliente de `/rfps/*` de la API principal.
 *
 * Único punto de la UI que llama a esas rutas. Pasa por `requestJson` (Bearer y
 * 401 → `/login`) y por el rewrite `/api/rfps*`. La subida responde `202` en
 * cuanto el ticket existe; el análisis corre en el worker y la UI consulta el
 * ticket cada pocos segundos mientras está en `analizando`.
 */
import { requestJson } from "@/lib/api-client";

const RFPS_API = "/api/rfps";

/** Mismo límite que `MAX_UPLOAD_BYTES` en la API. */
export const MAX_RFP_BYTES = 10 * 1024 * 1024;
/** Cada cuánto se consulta un ticket que sigue en `analizando`. */
export const RFP_POLL_INTERVAL_MS = 4000;

export type RfpTicketStatus = "analizando" | "descartado" | "analisis_completo";
export type RfpDepartmentId = "warehouse" | "lastmile" | "reverse";
export type RfpClientCountry = "US" | "ES";
export type RfpCurrency = "USD" | "EUR";
export type RfpService = "warehousing" | "last_mile" | "reverse_logistics";

export interface RfpTicketCreated {
  ticket_id: string;
  status: RfpTicketStatus;
  task_id: string;
}

export interface RfpTicketListItem {
  ticket_id: string;
  status: RfpTicketStatus;
  original_filename: string;
  client_name: string | null;
  client_country: RfpClientCountry | null;
  departments_needed: RfpDepartmentId[];
  attempts: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface RfpReadability {
  word_count: number;
  estimated_tokens: number;
  flesch_kincaid_grade: number | null;
  gunning_fog: number | null;
  flesch_reading_ease: number | null;
}

export interface RfpMetadata {
  rfp_id: string;
  client_name: string | null;
  client_country: RfpClientCountry | null;
  currency: RfpCurrency | null;
  client_reference: string | null;
  services_requested: RfpService[];
  monthly_volume: number | null;
  deadline: string | null;
  budget_range: string | null;
  departments_needed: RfpDepartmentId[];
  readability: RfpReadability;
}

export interface RfpDepartmentSection {
  department_id: RfpDepartmentId;
  department_name: string;
  responsible: string;
  key_aspects: string[];
  requested_inputs: string[];
  open_questions: string[];
}

export interface RfpSynthesis {
  summary: string;
  next_steps: string[];
  conflicts: string[];
  out_of_scope: string[];
}

export interface RfpTicket {
  ticket_id: string;
  status: RfpTicketStatus;
  original_filename: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  classification: { is_rfp: boolean; confidence: number; reason: string } | null;
  metadata: RfpMetadata | null;
  sections: RfpDepartmentSection[];
  synthesis: RfpSynthesis | null;
  handoff_ready: boolean;
}

export const rfpStatusLabels: Record<RfpTicketStatus, string> = {
  analizando: "Analizando",
  descartado: "Descartado",
  analisis_completo: "Análisis completo",
};

export const rfpDepartmentLabels: Record<RfpDepartmentId, string> = {
  warehouse: "Almacén",
  lastmile: "Última milla y transportistas",
  reverse: "Logística inversa",
};

export const rfpCountryLabels: Record<RfpClientCountry, string> = {
  US: "Estados Unidos",
  ES: "España",
};

export const rfpServiceLabels: Record<RfpService, string> = {
  warehousing: "Almacenamiento",
  last_mile: "Última milla",
  reverse_logistics: "Devoluciones",
};

/** Mensaje de validación local, o `null` si el archivo se puede subir. */
export function validateRfpFile(file: File | null): string | null {
  if (!file) return "Selecciona el PDF de la RFP.";
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "El archivo tiene que ser un PDF.";
  if (file.size === 0) return "El archivo está vacío.";
  if (file.size > MAX_RFP_BYTES) return "El PDF supera el tamaño máximo de 10 MB.";
  return null;
}

export async function uploadRfp(file: File): Promise<RfpTicketCreated> {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<RfpTicketCreated>(
    RFPS_API,
    { method: "POST", body: formData },
    "No se pudo registrar la RFP.",
  );
}

export async function listRfps(): Promise<RfpTicketListItem[]> {
  return requestJson<RfpTicketListItem[]>(RFPS_API, {}, "No se pudieron cargar las RFPs.");
}

export async function getRfp(ticketId: string): Promise<RfpTicket> {
  return requestJson<RfpTicket>(
    `${RFPS_API}/${encodeURIComponent(ticketId)}`,
    {},
    "No se pudo cargar la RFP.",
  );
}

export function formatRfpDate(value: string): string {
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

export function formatDeadline(value: string): string {
  // Fecha sin hora: se interpreta en UTC para que no cambie de día según la zona horaria.
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "long", timeZone: "UTC" }).format(
    new Date(`${value}T00:00:00Z`),
  );
}
