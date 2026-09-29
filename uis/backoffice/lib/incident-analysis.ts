export type IncidentCategory =
  | "LOST_PARCEL"
  | "DELAYED_DELIVERY"
  | "WRONG_ADDRESS"
  | "RETURN_REQUEST"
  | "DAMAGE";

export type IncidentStatus = "OPEN" | "CLOSED" | "DISCARDED";
export type IncidentCountry = "US" | "ES";

export interface IncidentBreakdownValue {
  count: number;
  percentage: number;
}

export interface IncidentAnalysisSummary {
  total_records: number;
  valid_records: number;
  invalid_records: number;
  invalid_breakdown: Record<string, { label: string; count: number }>;
  categories: Record<IncidentCategory, IncidentBreakdownValue>;
  statuses: Record<IncidentStatus, IncidentBreakdownValue>;
  countries: Record<IncidentCountry, IncidentBreakdownValue>;
  closed_incidents: number;
  scored_closed_incidents: number;
  average_satisfaction: number | null;
  satisfaction_scores: Record<"1" | "2" | "3" | "4" | "5", number>;
}

export const INCIDENT_CATEGORY_LABELS: Record<IncidentCategory, string> = {
  LOST_PARCEL: "Paquete perdido",
  DELAYED_DELIVERY: "Entrega retrasada",
  WRONG_ADDRESS: "Dirección incorrecta",
  RETURN_REQUEST: "Solicitud de devolución",
  DAMAGE: "Producto dañado",
};

export const INCIDENT_STATUS_LABELS: Record<IncidentStatus, string> = {
  OPEN: "Abiertas",
  CLOSED: "Cerradas",
  DISCARDED: "Descartadas",
};

export const INVALID_REASON_LABELS: Record<string, string> = {
  incident_id: "Identificador de incidencia inválido o ausente",
  date: "Fecha inválida o ausente",
  country: "País inválido o ausente",
  customer_type: "Tipo de cliente inválido o ausente",
  tracking_number: "Número de seguimiento ausente o demasiado corto",
  carrier_country: "Transportista no válido para el país",
  category: "Categoría inválida o ausente",
  description: "Descripción ausente o demasiado corta",
  customer_email: "Correo ausente o sin formato válido",
  status: "Estado inválido o ausente",
  satisfaction_score: "Puntuación de satisfacción fuera de rango",
  closed_without_score: "Incidencia cerrada sin puntuación",
};