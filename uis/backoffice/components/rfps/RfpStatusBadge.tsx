import { Badge } from "@/components/ui/Panel";
import {
  rfpApprovalStatusLabels,
  rfpSectionStatusLabels,
  rfpStatusLabels,
  type RfpApprovalStatus,
  type RfpSectionStatus,
  type RfpTicketStatus,
} from "@/lib/rfps";

type Tone = "info" | "danger" | "success" | "warning";

interface RfpStatusBadgeProps {
  status: RfpTicketStatus;
  /** El análisis o la generación fallaron en algún intento: el ticket no cambia de estado, pero hay que avisar. */
  hasError?: boolean;
}

const statusTones: Record<RfpTicketStatus, Tone> = {
  analizando: "info",
  descartado: "danger",
  analisis_completo: "success",
  generando_borrador: "info",
  en_evaluación: "info",
  needs_human_review: "warning",
  esperando_aprobación: "warning",
  terminado: "success",
};

export function RfpStatusBadge({ status, hasError = false }: RfpStatusBadgeProps) {
  if (hasError && statusTones[status] !== "danger") {
    return <Badge tone="warning">{rfpStatusLabels[status]} · con errores</Badge>;
  }
  return <Badge tone={statusTones[status]}>{rfpStatusLabels[status]}</Badge>;
}

const sectionTones: Record<RfpSectionStatus, Tone> = {
  generando_borrador: "info",
  en_evaluación: "info",
  evaluacion_superada: "success",
  needs_human_review: "warning",
};

export function RfpSectionStatusBadge({ status }: { status: RfpSectionStatus }) {
  return <Badge tone={sectionTones[status]}>{rfpSectionStatusLabels[status]}</Badge>;
}

const approvalTones: Record<RfpApprovalStatus, Tone> = {
  pendiente: "warning",
  cambios_solicitados: "info",
  aprobada: "success",
  rechazada: "danger",
};

export function RfpApprovalStatusBadge({ status }: { status: RfpApprovalStatus }) {
  return <Badge tone={approvalTones[status]}>{rfpApprovalStatusLabels[status]}</Badge>;
}
