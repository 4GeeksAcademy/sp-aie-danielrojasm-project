"use client";

import { useState, type FormEvent } from "react";
import { Panel } from "@/components/ui/Panel";
import { getUserMessage } from "@/lib/api-client";
import {
  askKnowledgeBase,
  exampleQuestions,
  QUESTION_MAX_LENGTH,
  validateQuestion,
} from "@/lib/knowledge";

const FALLBACK_ERROR = "No se pudo obtener una respuesta del asistente comercial. Inténtalo de nuevo.";

interface AnsweredQuestion {
  question: string;
  answer: string;
}

export function KnowledgeAssistant() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnsweredQuestion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function ask(text: string) {
    const validation = validateQuestion(text);
    setError(validation);
    if (validation || loading) return;
    setLoading(true);
    setResult(null);
    try {
      const { answer } = await askKnowledgeBase(text);
      setResult({ question: text.trim(), answer });
    } catch (caught) {
      setError(getUserMessage(caught, FALLBACK_ERROR));
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(question);
  }

  function askExample(example: string) {
    setQuestion(example);
    void ask(example);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">
          Comercial · Base de conocimiento
        </p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">Asistente comercial</h1>
        <p className="mt-2 text-sm text-slate-600">
          Pregunta por SLA de entrega, devoluciones, cobertura de transportistas o tarifas de
          almacenamiento. La respuesta se redacta a partir de los acuerdos estándar de TrackFlow y
          cita su fuente; descuentos y excepciones siguen necesitando aprobación.
        </p>
      </header>

      <Panel id="knowledge-question" title="Pregunta del cliente">
        <form onSubmit={handleSubmit} noValidate className="space-y-4">
          <div>
            <label htmlFor="question" className="block text-sm font-semibold text-slate-800">
              ¿Qué te ha preguntado la marca?
            </label>
            <textarea
              id="question"
              name="question"
              rows={3}
              maxLength={QUESTION_MAX_LENGTH}
              value={question}
              onChange={(event) => {
                setQuestion(event.target.value);
                setError(null);
              }}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "question-error" : "question-hint"}
              placeholder="Ej.: ¿qué compensación recibe el cliente si no se cumple el SLA?"
              className={`mt-2 block w-full rounded-lg border bg-white px-4 py-3 text-base text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-cyan-500 ${
                error ? "border-rose-400" : "border-slate-300"
              }`}
            />
            {error ? (
              <p id="question-error" role="alert" className="mt-1.5 text-sm font-medium text-rose-700">
                {error}
              </p>
            ) : (
              <p id="question-hint" className="mt-1.5 text-sm text-slate-500">
                Escribe la pregunta tal como la haría el cliente.
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={loading}
              className="rounded-md bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-wait disabled:opacity-60"
            >
              {loading ? "Consultando…" : "Preguntar"}
            </button>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Preguntas frecuentes</p>
            <ul className="mt-2 flex flex-wrap gap-2">
              {exampleQuestions.map((example) => (
                <li key={example}>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => askExample(example)}
                    className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:border-cyan-500 hover:text-cyan-800 disabled:opacity-60"
                  >
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </form>
      </Panel>

      <div aria-live="polite">
        {loading ? (
          <p className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-sm">
            Buscando en la base de conocimiento y redactando la respuesta…
          </p>
        ) : null}
        {result ? (
          <Panel
            id="knowledge-answer"
            title="Respuesta sugerida"
            description={`Pregunta: ${result.question}`}
          >
            <p className="whitespace-pre-line text-base leading-relaxed text-slate-800">{result.answer}</p>
          </Panel>
        ) : null}
      </div>
    </div>
  );
}
