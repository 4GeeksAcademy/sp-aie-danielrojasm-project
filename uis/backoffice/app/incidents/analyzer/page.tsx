import type { Metadata } from "next";
import { IncidentAnalysis } from "@/components/incidents/IncidentAnalysis";

export const metadata: Metadata = { title: "Análisis CSV de incidencias" };

export default function IncidentAnalyzerPage() {
  return <IncidentAnalysis />;
}
