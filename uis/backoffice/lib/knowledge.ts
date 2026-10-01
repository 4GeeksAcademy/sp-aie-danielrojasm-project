/**
 * Asistente comercial (RAG): cliente de `POST /knowledge/query`.
 *
 * Único punto de la UI que llama a la base de conocimiento. Pasa por `requestJson`
 * (Bearer y 401 → `/login`) y por el rewrite `/api/knowledge/*`. La API solo
 * devuelve la respuesta generada: ni fragmentos ni puntuaciones.
 */
import { requestJson } from "@/lib/api-client";

const KNOWLEDGE_API = "/api/knowledge/query";

/** Mismos límites que `KnowledgeQueryRequest` en la API. */
export const QUESTION_MIN_LENGTH = 3;
export const QUESTION_MAX_LENGTH = 1000;

export interface KnowledgeAnswer {
  answer: string;
}

/** Preguntas habituales de marcas cliente y prospectos, como atajo. */
export const exampleQuestions: readonly string[] = [
  "¿Cuál es la ventana de devolución estándar?",
  "¿Qué transportista cubre mejor Aragón rural?",
  "¿Garantizamos los plazos de entrega en Black Friday?",
  "¿Cuánto cuesta almacenar un metro cúbico al mes en Zaragoza?",
];

/** Mensaje de validación local, o `null` si la pregunta se puede enviar. */
export function validateQuestion(question: string): string | null {
  const length = question.trim().length;
  if (length < QUESTION_MIN_LENGTH) return "Escribe la pregunta que te ha hecho el cliente.";
  if (length > QUESTION_MAX_LENGTH) {
    return `La pregunta no puede superar los ${QUESTION_MAX_LENGTH} caracteres.`;
  }
  return null;
}

export async function askKnowledgeBase(question: string): Promise<KnowledgeAnswer> {
  return requestJson<KnowledgeAnswer>(
    KNOWLEDGE_API,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question.trim() }),
    },
    "No se pudo obtener una respuesta del asistente comercial.",
  );
}
