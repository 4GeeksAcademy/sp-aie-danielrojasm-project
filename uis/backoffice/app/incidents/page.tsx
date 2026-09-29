import type { Metadata } from "next";
import { IncidentManager } from "@/components/incidents/IncidentManager";

export const metadata: Metadata = { title: "Panel de incidencias" };

export default function IncidentsPage() {
  return <IncidentManager />;
}
