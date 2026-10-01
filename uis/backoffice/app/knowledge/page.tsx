import type { Metadata } from "next";
import { KnowledgeAssistant } from "@/components/knowledge/KnowledgeAssistant";

export const metadata: Metadata = { title: "Asistente comercial" };

export default function KnowledgePage() {
  return <KnowledgeAssistant />;
}
