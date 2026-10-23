import { Badge } from "@/components/ui/Panel";
import { rfpStatusLabels, type RfpTicketStatus } from "@/lib/rfps";

interface RfpStatusBadgeProps {
  status: RfpTicketStatus;
  /** El análisis falló en algún intento: el ticket sigue en `analizando`, pero hay que avisar. */
  hasError?: boolean;
}

const statusTones: Record<RfpTicketStatus, "info" | "danger" | "success"> = {
  analizando: "info",
  descartado: "danger",
  analisis_completo: "success",
};

export function RfpStatusBadge({ status, hasError = false }: RfpStatusBadgeProps) {
  if (status === "analizando" && hasError) {
    return <Badge tone="warning">{rfpStatusLabels.analizando} · con errores</Badge>;
  }
  return <Badge tone={statusTones[status]}>{rfpStatusLabels[status]}</Badge>;
}
