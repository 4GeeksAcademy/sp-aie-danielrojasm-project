import type { Metadata } from "next";
import { WeeklyPerformanceDashboard } from "@/components/reporting/WeeklyPerformanceDashboard";

export const metadata: Metadata = { title: "Reporte semanal de desempeño" };

export default function ReportingPage() {
  return <WeeklyPerformanceDashboard />;
}
