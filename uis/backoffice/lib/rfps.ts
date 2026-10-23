/**
 * Recepción de RFPs en modo ticket: cliente de `/rfps/*` de la API principal.
 *
 * Único punto de la UI que llama a esas rutas. Pasa por `requestJson` (Bearer y
 * 401 → `/login`) y por el rewrite `/api/rfps*`. La subida responde `202` en
 * cuanto el ticket existe; el análisis y la generación de borradores corren en el
 * worker y la UI consulta el ticket cada pocos segundos mientras siguen en curso
 * (`isRfpInProgress`) o mientras espera la aprobación de algún responsable.
 * La decisión de cada responsable (Parte 3) también responde `202`: el worker
 * reanuda solo la rama de ese departamento.
 */
import { requestJson } from "@/lib/api-client";

const RFPS_API = "/api/rfps";

/** Mismo límite que `MAX_UPLOAD_BYTES` en la API. */
export const MAX_RFP_BYTES = 10 * 1024 * 1024;
/** Cada cuánto se consulta un ticket que sigue en curso. */
export const RFP_POLL_INTERVAL_MS = 4000;

export type RfpTicketStatus =
  | "analizando"
  | "descartado"
  | "analisis_completo"
  | "generando_borrador"
  | "en_evaluación"
  | "needs_human_review"
  | "esperando_aprobación"
  | "terminado";
export type RfpApprovalStatus = "pendiente" | "cambios_solicitados" | "aprobada" | "rechazada";
export type RfpDecision = "approve" | "request_changes" | "reject";
export type RfpTriggerId = "volume-vs-capacity" | "returns-sla-breach" | "currency-mismatch";
export type RfpTracePart = "parte_1" | "parte_2" | "parte_3";
export type RfpSectionStatus =
  | "generando_borrador"
  | "en_evaluación"
  | "evaluacion_superada"
  | "needs_human_review";
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
  response_handoff_ready: boolean;
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
  draft_status: RfpSectionStatus | null;
  iterations: number;
  draft_content: string | null;
  evaluation: RfpEvaluationResult | null;
  approval_status: RfpApprovalStatus | null;
  approver: string | null;
  approved_at: string | null;
  review_round: number;
  revisions: number;
  approval_history: RfpApprovalDecisionRecord[];
  pending_review: RfpPendingReview | null;
}

/** Revisión esperando al responsable: el valor del `interrupt` de su rama. */
export interface RfpPendingReview {
  approver: string;
  review_round: number;
  revisions: number;
  max_rounds: number;
  evaluation_pass: boolean | null;
  failed_rules: string[];
  arbitration_notes: string[];
  allowed_decisions: RfpDecision[];
}

export interface RfpApprovalDecisionRecord {
  decision: RfpDecision;
  review_round: number;
  comment: string;
  decided_by: string;
  approver: string;
  decided_at: string;
  committed_monthly_capacity: number | null;
}

export interface RfpDecisionInput {
  decision: RfpDecision;
  review_round: number;
  comment: string;
  committed_monthly_capacity?: number;
}

export interface RfpArbitration {
  round: number;
  trigger_id: RfpTriggerId;
  arbiter: string;
  rule: string;
  department_id: RfpDepartmentId;
  action: "request_changes" | "reject";
  instruction: string | null;
  evidence: string;
  decided_at: string;
}

export interface RfpTraceEntry {
  part: RfpTracePart;
  node: string;
  agent: string;
  department_id: string | null;
  input: unknown;
  output: unknown;
  timestamp: string;
  duration_ms: number | null;
}

export interface RfpFinalDocument {
  ticket_id: string;
  rfp_id: string | null;
  currency: RfpCurrency;
  generated_at: string;
  sections: {
    department_id: RfpDepartmentId;
    department_name: string;
    approver: string;
    approved_at: string;
    review_round: number;
  }[];
  content: string;
}

export interface RfpComplianceViolation {
  rule_id: string;
  detail: string;
  evidence: string;
  source: string;
}

/** `EvaluationResult` de la Parte 2 tal como lo persiste el pipeline. */
export interface RfpEvaluationResult {
  section_id: string;
  department_id: RfpDepartmentId;
  iteration: number;
  readability: { pass: boolean; score: number | null; details: string };
  relevance: { pass: boolean; missing_aspects: string[]; checked_aspects: number };
  compliance: {
    pass: boolean;
    rule_ids: string[];
    violations: RfpComplianceViolation[];
    checked_rule_ids: string[];
  };
  overall_pass: boolean;
  feedback_for_generator: string;
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
  generation_attempts: number;
  max_iterations: number | null;
  response_handoff_ready: boolean;
  approval_attempts: number;
  arbitrations: RfpArbitration[];
  trace: RfpTraceEntry[];
  final_document_ready: boolean;
}

export interface RfpDecisionAccepted {
  ticket_id: string;
  department_id: RfpDepartmentId;
  task_id: string;
}

export const rfpStatusLabels: Record<RfpTicketStatus, string> = {
  analizando: "Analizando",
  descartado: "Descartado",
  analisis_completo: "Análisis completo",
  generando_borrador: "Generando borrador",
  en_evaluación: "En evaluación",
  needs_human_review: "Requiere revisión humana",
  esperando_aprobación: "Esperando aprobación",
  terminado: "Terminado",
};

export const rfpApprovalStatusLabels: Record<RfpApprovalStatus, string> = {
  pendiente: "Pendiente de aprobación",
  cambios_solicitados: "Cambios solicitados",
  aprobada: "Aprobada",
  rechazada: "Rechazada",
};

export const rfpDecisionLabels: Record<RfpDecision, string> = {
  approve: "Aprobar",
  request_changes: "Pedir cambios",
  reject: "Rechazar",
};

/** Triggers de conflicto del BRIEFING §7 que resuelve el árbitro fijo. */
export const rfpTriggerLabels: Record<RfpTriggerId, string> = {
  "volume-vs-capacity": "Volumen por encima de la capacidad de almacén",
  "returns-sla-breach": "Devoluciones prometidas en menos de 48 horas",
  "currency-mismatch": "Monedas distintas entre secciones o frente al país",
};

export const rfpArbitrationActionLabels: Record<RfpArbitration["action"], string> = {
  request_changes: "Cambios obligatorios",
  reject: "Sección rechazada",
};

export const rfpTracePartLabels: Record<RfpTracePart, string> = {
  parte_1: "Recepción",
  parte_2: "Generación",
  parte_3: "Aprobación",
};

export const rfpSectionStatusLabels: Record<RfpSectionStatus, string> = {
  generando_borrador: "Generando borrador",
  en_evaluación: "En evaluación",
  evaluacion_superada: "Evaluación superada",
  needs_human_review: "Borrador provisional · requiere revisión humana",
};

/** Lineamientos del BRIEFING §5 que verifica el evaluador de cumplimiento. */
export const rfpComplianceRuleLabels: Record<string, string> = {
  "currency-by-country": "Moneda según el país del cliente",
  "on-time-sla": "SLA de entrega a tiempo (%)",
  "returns-min-48h": "Devoluciones nunca en menos de 48 horas",
  "volume-discount-table": "Tabla de descuentos por volumen",
  "no-carrier-rates": "Sin tarifas negociadas con transportistas",
};

const RFP_ACTIVE_STATUSES: ReadonlySet<RfpTicketStatus> = new Set([
  "analizando",
  "generando_borrador",
  "en_evaluación",
  "needs_human_review",
]);

/**
 * El worker sigue trabajando en el ticket: análisis, generación o, con el
 * handoff de la Parte 2 ya guardado (`en_evaluación` / `needs_human_review`),
 * la apertura de la aprobación por departamento.
 */
export function isRfpInProgress(status: RfpTicketStatus): boolean {
  return RFP_ACTIVE_STATUSES.has(status);
}

/** La Parte 2 terminó y el worker está abriendo la revisión de cada responsable. */
export function isRfpOpeningApproval(status: RfpTicketStatus, responseHandoffReady: boolean): boolean {
  return responseHandoffReady && (status === "en_evaluación" || status === "needs_human_review");
}

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

export async function submitRfpDecision(
  ticketId: string,
  departmentId: RfpDepartmentId,
  input: RfpDecisionInput,
): Promise<RfpDecisionAccepted> {
  return requestJson<RfpDecisionAccepted>(
    `${RFPS_API}/${encodeURIComponent(ticketId)}/sections/${departmentId}/decision`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) },
    "No se pudo registrar la decisión.",
  );
}

export async function getRfpDocument(ticketId: string): Promise<RfpFinalDocument> {
  return requestJson<RfpFinalDocument>(
    `${RFPS_API}/${encodeURIComponent(ticketId)}/document`,
    {},
    "No se pudo cargar el documento final.",
  );
}

/** Mensaje de validación local de una decisión, o `null` si se puede enviar. */
export function validateRfpDecision(decision: RfpDecision, comment: string): string | null {
  if (decision !== "approve" && comment.trim().length < 10) {
    return "Explica el motivo (al menos 10 caracteres): el generador y Ventas lo usan.";
  }
  return null;
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
