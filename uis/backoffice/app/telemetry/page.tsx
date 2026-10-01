import type { Metadata } from "next";
import { TelemetryReportView } from "@/components/telemetry/TelemetryReportView";

export const metadata: Metadata = { title: "Reporte técnico de telemetría" };

export default function TelemetryPage() {
  return <TelemetryReportView />;
}
