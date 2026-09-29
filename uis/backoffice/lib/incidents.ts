/**
 * Gestor de incidencias: tipos, etiquetas y cliente de `/api/incidents`.
 * Los valores coinciden con `packages/shared/incidents/domain.py`; la API es la
 * que valida. Aquí solo se replica lo necesario para guiar al usuario.
 */
import { ApiError, requestJson } from "@/lib/api-client";

export type IncidentCategory =
  | "lost_parcel"
  | "delivery_failure"
  | "inventory_discrepancy"
  | "carrier_issue"
  | "returns_issue"
  | "warehouse_incident"
  | "system_failure"
  | "client_complaint"
  | "other";

export type IncidentStatus = "open" | "in_progress" | "resolved" | "discarded";
export type IncidentOrigin = "customer" | "branch" | "internal";
export type Branch =
  | "central"
  | "la_warehouse"
  | "la_office"
  | "zaragoza_warehouse"
  | "zaragoza_office";

export interface Incident {
  id: number;
  title: string;
  description: string;
  category: IncidentCategory;
  status: IncidentStatus;
  origin: IncidentOrigin;
  branch: Branch;
  reported_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface IncidentCreatePayload {
  title: string;
  description: string;
  category: IncidentCategory;
  origin: IncidentOrigin;
  branch: Branch;
  status: "open";
}

export interface IncidentSummary {
  total: number;
  by_status: Record<IncidentStatus, number>;
  by_category: Record<IncidentCategory, number>;
  by_origin: Record<IncidentOrigin, number>;
  by_branch: Record<Branch, number>;
}

export interface IncidentFilters {
  status: IncidentStatus | "";
  origin: IncidentOrigin | "";
  branch: Branch | "";
  category: IncidentCategory | "";
}

export const incidentCategoryLabels: Record<IncidentCategory, string> = {
  lost_parcel: "Paquete extraviado",
  delivery_failure: "Fallo de entrega",
  inventory_discrepancy: "Descuadre de inventario",
  carrier_issue: "Problema de carrier",
  returns_issue: "Problema de devolución",
  warehouse_incident: "Incidente en almacén",
  system_failure: "Fallo de sistema",
  client_complaint: "Queja de cliente",
  other: "Otra",
};

export const incidentCategoryHints: Record<IncidentCategory, string> = {
  lost_parcel: "Paquete extraviado en tránsito o en almacén.",
  delivery_failure:
    "Intento fallido, dirección incorrecta o cliente ausente no gestionado.",
  inventory_discrepancy: "Diferencia entre stock registrado y stock físico.",
  carrier_issue: "Retraso, daño o incumplimiento de SLA de un carrier.",
  returns_issue: "Problema en la devolución o la logística inversa.",
  warehouse_incident:
    "Daño de mercancía, accidente o fallo de equipamiento en almacén.",
  system_failure: "Fallo en WMS, integraciones o API de carrier.",
  client_complaint: "Queja de una empresa cliente sobre el servicio.",
  other: "No encaja en ninguna de las categorías anteriores.",
};

export const incidentStatusLabels: Record<IncidentStatus, string> = {
  open: "Abierta",
  in_progress: "En curso",
  resolved: "Resuelta",
  discarded: "Descartada",
};

export const incidentOriginLabels: Record<IncidentOrigin, string> = {
  customer: "Cliente",
  branch: "Sede",
  internal: "Interno",
};

export const incidentOriginHints: Record<IncidentOrigin, string> = {
  customer: "Empresa cliente o consumidor final",
  branch: "Personal de almacén u oficina",
  internal: "Tecnología, dirección u operaciones",
};

export const branchLabels: Record<Branch, string> = {
  central: "Central",
  la_warehouse: "Los Ángeles — Almacén",
  la_office: "Los Ángeles — Oficina",
  zaragoza_warehouse: "Zaragoza — Almacén",
  zaragoza_office: "Zaragoza — Oficina",
};

export const incidentCategories = Object.keys(
  incidentCategoryLabels,
) as IncidentCategory[];
export const incidentStatuses = Object.keys(
  incidentStatusLabels,
) as IncidentStatus[];
export const incidentOrigins = Object.keys(
  incidentOriginLabels,
) as IncidentOrigin[];
export const branches = Object.keys(branchLabels) as Branch[];

/** Categorías con impacto directo en el SLA con clientes (CONTEXT). */
export const slaCategories: ReadonlySet<IncidentCategory> = new Set([
  "lost_parcel",
  "carrier_issue",
]);

/** Ciclo de vida: la API aplica la misma regla y responde 400 si no se cumple. */
export const nextStatuses: Record<IncidentStatus, IncidentStatus[]> = {
  open: ["in_progress", "discarded"],
  in_progress: ["resolved", "discarded"],
  resolved: [],
  discarded: [],
};

export const TITLE_MAX_LENGTH = 120;

// ---------------------------------------------------------------------------
// Validación en cliente
// ---------------------------------------------------------------------------

export interface IncidentFormValues {
  title: string;
  description: string;
  category: IncidentCategory | "";
  origin: IncidentOrigin | "";
  branch: Branch | "";
}

export type IncidentFormField = keyof IncidentFormValues;
export type IncidentFormErrors = Partial<Record<IncidentFormField, string>>;

/** Mensajes propios de la UI: nunca se muestra el texto técnico de la API. */
export const incidentFieldMessages: Record<IncidentFormField, string> = {
  title: `Escribe un título breve (máximo ${TITLE_MAX_LENGTH} caracteres).`,
  description: "Describe qué ha pasado para que el equipo pueda actuar.",
  category: "Selecciona una categoría de la lista.",
  origin: "Indica quién detectó o comunicó la incidencia.",
  branch: "Selecciona la sede que gestiona la incidencia (o Central).",
};

export function validateIncidentForm(
  values: IncidentFormValues,
): IncidentFormErrors {
  const errors: IncidentFormErrors = {};
  const title = values.title.trim();
  if (!title || title.length > TITLE_MAX_LENGTH) {
    errors.title = incidentFieldMessages.title;
  }
  if (!values.description.trim()) {
    errors.description = incidentFieldMessages.description;
  }
  if (!values.category) errors.category = incidentFieldMessages.category;
  if (!values.origin) errors.origin = incidentFieldMessages.origin;
  if (!values.branch) errors.branch = incidentFieldMessages.branch;
  return errors;
}

// ---------------------------------------------------------------------------
// Errores de API → mensajes comprensibles
// ---------------------------------------------------------------------------

export interface FriendlyError {
  message: string;
  fields: IncidentFormErrors;
}

function isFormField(value: string): value is IncidentFormField {
  return value in incidentFieldMessages;
}

export function toFriendlyError(error: unknown, action: string): FriendlyError {
  if (!(error instanceof ApiError)) {
    return {
      message: `No se pudo ${action}: no hay conexión con el servicio de incidencias. Comprueba tu red e inténtalo de nuevo.`,
      fields: {},
    };
  }
  if (error.status === 400) {
    const fields: IncidentFormErrors = {};
    for (const item of error.body?.errors ?? []) {
      if (isFormField(item.field)) fields[item.field] = incidentFieldMessages[item.field];
    }
    return {
      message:
        Object.keys(fields).length > 0
          ? "Revisa los campos marcados antes de volver a enviar."
          : `No se pudo ${action}: algunos datos no son válidos.`,
      fields,
    };
  }
  if (error.status === 404) {
    return {
      message: "La incidencia ya no existe. Recarga el listado para ver los datos actuales.",
      fields: {},
    };
  }
  if (error.status === 401) {
    return { message: "Tu sesión ha caducado. Vuelve a iniciar sesión.", fields: {} };
  }
  return {
    message: `No se pudo ${action}: el servicio de incidencias no responde ahora mismo. Inténtalo de nuevo en unos minutos.`,
    fields: {},
  };
}

// ---------------------------------------------------------------------------
// Cliente HTTP
// ---------------------------------------------------------------------------

const BASE_PATH = "/api/incidents";
const JSON_HEADERS = { "Content-Type": "application/json" };

export function fetchIncidents(filters: IncidentFilters): Promise<Incident[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return requestJson<Incident[]>(query ? `${BASE_PATH}?${query}` : BASE_PATH);
}

export function fetchIncidentSummary(): Promise<IncidentSummary> {
  return requestJson<IncidentSummary>(`${BASE_PATH}/summary`);
}

export function createIncident(payload: IncidentCreatePayload): Promise<Incident> {
  return requestJson<Incident>(BASE_PATH, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function updateIncidentStatus(
  id: number,
  status: IncidentStatus,
): Promise<Incident> {
  return requestJson<Incident>(`${BASE_PATH}/${id}/status`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify({ status }),
  });
}

const dateTimeFormatter = new Intl.DateTimeFormat("es-ES", {
  dateStyle: "medium",
  timeStyle: "short",
});

export function formatIncidentDate(value: string): string {
  return dateTimeFormatter.format(new Date(value));
}
