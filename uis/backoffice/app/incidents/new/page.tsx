import type { Metadata } from "next";
import { IncidentForm } from "@/components/incidents/IncidentForm";

export const metadata: Metadata = { title: "Registrar incidencia" };

export default function NewIncidentPage() {
  return <IncidentForm />;
}
