"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { RfpSectionStatusBadge, RfpStatusBadge } from "@/components/rfps/RfpStatusBadge";
import { Panel } from "@/components/ui/Panel";
import { getUserMessage } from "@/lib/api-client";
import {
  formatDeadline,
  formatRfpDate,
  getRfp,
  isRfpInProgress,
  rfpComplianceRuleLabels,
  rfpCountryLabels,
  rfpDepartmentLabels,
  RFP_POLL_INTERVAL_MS,
  rfpServiceLabels,
  type RfpDepartmentSection,
  type RfpEvaluationResult,
  type RfpMetadata,
  type RfpTicket,
} from "@/lib/rfps";

const LOAD_FALLBACK_ERROR = "No se pudo cargar la RFP.";

interface RfpTicketDetailProps {
  ticketId: string;
}

export function RfpTicketDetail({ ticketId }: RfpTicketDetailProps) {
  const [ticket, setTicket] = useState<RfpTicket | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  // Carga inicial y consulta periódica mientras el análisis o la generación siguen en curso.
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const load = async () => {
      try {
        const loaded = await getRfp(ticketId);
        if (!active) return;
        setTicket(loaded);
        setError("");
        if (isRfpInProgress(loaded.status, loaded.response_handoff_ready)) {
          timer = window.setTimeout(load, RFP_POLL_INTERVAL_MS);
        }
      } catch (caught) {
        if (active) setError(getUserMessage(caught, LOAD_FALLBACK_ERROR));
      }
    };
    void load();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [ticketId, attempt]);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <Link href="/rfps" className="text-sm font-medium text-cyan-800 hover:underline">
        ← Volver a la recepción de RFPs
      </Link>
      {error ? <RetryAlert message={error} onRetry={() => setAttempt((value) => value + 1)} /> : null}
      {!ticket && !error ? (
        <p className="text-sm text-slate-500" role="status">
          Cargando la RFP…
        </p>
      ) : null}
      {ticket ? <TicketView ticket={ticket} /> : null}
    </div>
  );
}

interface TicketViewProps {
  ticket: RfpTicket;
}

function TicketView({ ticket }: TicketViewProps) {
  const analyzed = ticket.status !== "analizando" && ticket.status !== "descartado";
  const generating = analyzed && isRfpInProgress(ticket.status, ticket.response_handoff_ready);
  const drafts = ticket.sections.filter((section) => section.draft_status !== null);
  const provisional = drafts.filter((section) => section.draft_status === "needs_human_review");
  return (
    <>
      <header className="space-y-2">
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">Ticket de RFP</p>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold text-slate-950">
            {ticket.metadata?.client_name ?? ticket.original_filename}
          </h1>
          <RfpStatusBadge status={ticket.status} hasError={Boolean(ticket.last_error)} />
        </div>
        <p className="text-sm text-slate-600">
          {ticket.original_filename} · recibida el {formatRfpDate(ticket.created_at)}
        </p>
      </header>

      <div aria-live="polite" className="space-y-4">
        {ticket.status === "analizando" ? (
          <p className="rounded-lg border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-900" role="status">
            Analizando el documento: conversión a texto, clasificación y análisis por departamento. Esta página se
            actualiza sola.
          </p>
        ) : null}
        {generating ? (
          <p className="rounded-lg border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-900" role="status">
            Generando el borrador de la propuesta económica: cada departamento redacta su sección y tres evaluadores
            (legibilidad, pertinencia y cumplimiento) la revisan. Esta página se actualiza sola.
          </p>
        ) : null}
        {ticket.status === "needs_human_review" ? (
          <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <p className="font-semibold">
              {provisional.length === 1 ? "Una sección no superó" : `${provisional.length} secciones no superaron`} la
              evaluación tras {ticket.max_iterations ?? "el límite de"} iteraciones. Su borrador es provisional: revisa
              los fallos indicados antes de enviarlo al cliente.
            </p>
            <p className="mt-1">
              {provisional.map((section) => rfpDepartmentLabels[section.department_id]).join(", ")}
            </p>
          </div>
        ) : null}
        {ticket.status === "en_evaluación" && ticket.response_handoff_ready ? (
          <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900" role="status">
            Todas las secciones superaron la evaluación y están listas para la aprobación de cada responsable.
          </p>
        ) : null}
        {ticket.last_error ? (
          <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <p className="font-semibold">
              {ticket.status === "analizando"
                ? `El análisis falló en el intento ${ticket.attempts}.`
                : `La generación de borradores falló en el intento ${ticket.generation_attempts}.`}{" "}
              Se reintenta automáticamente; si no avanza, avisa al equipo técnico con el ticket {ticket.ticket_id}.
            </p>
            <p className="mt-1">{ticket.last_error}</p>
          </div>
        ) : null}
      </div>

      {ticket.status === "descartado" && ticket.classification ? (
        <Panel id="rfp-discarded" title="Documento descartado" description="El clasificador decidió que no es una RFP de cliente.">
          <p className="text-sm text-slate-800">{ticket.classification.reason}</p>
          <p className="mt-2 text-xs text-slate-500">
            Confianza del clasificador: {formatPercent(ticket.classification.confidence)}. Si es una RFP real,
            avisa al equipo técnico con el ticket {ticket.ticket_id} para reprocesarla.
          </p>
        </Panel>
      ) : null}

      {analyzed && ticket.metadata ? (
        <>
          {ticket.synthesis ? (
            <Panel id="rfp-summary" title="Resumen para Ventas">
              <p className="text-base leading-relaxed text-slate-800">{ticket.synthesis.summary}</p>
              <TextList title="Siguientes pasos" items={ticket.synthesis.next_steps} />
              <TextList title="Contradicciones detectadas" items={ticket.synthesis.conflicts} tone="warning" />
              <TextList title="Fuera del alcance de los departamentos" items={ticket.synthesis.out_of_scope} />
            </Panel>
          ) : null}
          <MetadataPanel metadata={ticket.metadata} />
          <section aria-labelledby="rfp-departments-title" className="space-y-4">
            <h2 id="rfp-departments-title" className="text-lg font-semibold text-slate-900">
              Qué le toca a cada departamento
            </h2>
            {ticket.sections.length === 0 ? (
              <p className="text-sm text-slate-500">Ningún departamento aplica a lo que pide el cliente.</p>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">
                {ticket.sections.map((section) => (
                  <DepartmentCard key={section.department_id} section={section} />
                ))}
              </div>
            )}
          </section>
          {drafts.length > 0 ? (
            <section aria-labelledby="rfp-drafts-title" className="space-y-4">
              <h2 id="rfp-drafts-title" className="text-lg font-semibold text-slate-900">
                Borrador de la propuesta económica
              </h2>
              {drafts.map((section) => (
                <DraftCard key={section.department_id} section={section} />
              ))}
            </section>
          ) : null}
          {ticket.handoff_ready && drafts.length === 0 ? (
            <p className="text-xs text-slate-500">
              Handoff listo para la generación de la propuesta (ticket {ticket.ticket_id}).
            </p>
          ) : null}
        </>
      ) : null}
    </>
  );
}

interface MetadataPanelProps {
  metadata: RfpMetadata;
}

function MetadataPanel({ metadata }: MetadataPanelProps) {
  const { readability } = metadata;
  const rows: { label: string; value: string }[] = [
    { label: "Cliente", value: metadata.client_name ?? "No indicado" },
    {
      label: "País y moneda",
      value: metadata.client_country
        ? `${rfpCountryLabels[metadata.client_country]} · ${metadata.currency ?? "—"}`
        : "No indicado",
    },
    { label: "Referencia", value: metadata.client_reference ?? "Sin referencia" },
    {
      label: "Servicios solicitados",
      value: metadata.services_requested.map((service) => rfpServiceLabels[service]).join(", ") || "No indicados",
    },
    {
      label: "Volumen mensual",
      value:
        metadata.monthly_volume !== null
          ? `${new Intl.NumberFormat("es-ES").format(metadata.monthly_volume)} pedidos/mes`
          : "No indicado",
    },
    { label: "Fecha límite", value: metadata.deadline ? formatDeadline(metadata.deadline) : "No indicada" },
    { label: "Presupuesto de referencia", value: metadata.budget_range ?? "No indicado" },
    {
      label: "Costo de procesamiento",
      value: `${new Intl.NumberFormat("es-ES").format(readability.word_count)} palabras · ~${new Intl.NumberFormat("es-ES").format(readability.estimated_tokens)} tokens`,
    },
    {
      label: "Legibilidad",
      value:
        readability.flesch_kincaid_grade !== null
          ? `Flesch-Kincaid ${formatScore(readability.flesch_kincaid_grade)} · Gunning Fog ${formatScore(readability.gunning_fog)} · Flesch ${formatScore(readability.flesch_reading_ease)}`
          : "Documento demasiado corto para medirla (menos de 100 palabras)",
    },
  ];
  return (
    <Panel id="rfp-metadata" title="Datos de la RFP">
      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
        {rows.map((row) => (
          <div key={row.label}>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{row.label}</dt>
            <dd className="mt-0.5 text-sm text-slate-900">{row.value}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

interface DepartmentCardProps {
  section: RfpDepartmentSection;
}

function DepartmentCard({ section }: DepartmentCardProps) {
  const headingId = `rfp-department-${section.department_id}`;
  return (
    <section aria-labelledby={headingId} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 id={headingId} className="text-base font-semibold text-slate-900">
        {rfpDepartmentLabels[section.department_id]}
      </h3>
      <p className="text-sm text-slate-600">
        Pedírselo a <span className="font-semibold text-slate-900">{section.responsible}</span>
      </p>
      <TextList title="Aspectos clave" items={section.key_aspects} />
      <TextList title={`Qué pedirle a ${section.responsible}`} items={section.requested_inputs} />
      <TextList title="Preguntas abiertas para el cliente" items={section.open_questions} tone="warning" />
    </section>
  );
}

interface DraftCardProps {
  section: RfpDepartmentSection;
}

function DraftCard({ section }: DraftCardProps) {
  const headingId = `rfp-draft-${section.department_id}`;
  const provisional = section.draft_status === "needs_human_review";
  return (
    <section
      aria-labelledby={headingId}
      className={`rounded-xl border bg-white p-5 shadow-sm ${provisional ? "border-amber-300" : "border-slate-200"}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={headingId} className="text-base font-semibold text-slate-900">
          {rfpDepartmentLabels[section.department_id]}
        </h3>
        <div className="flex items-center gap-2">
          {section.draft_status ? <RfpSectionStatusBadge status={section.draft_status} /> : null}
          <span className="text-xs text-slate-500">
            {section.iterations} {section.iterations === 1 ? "iteración" : "iteraciones"}
          </span>
        </div>
      </div>
      {section.draft_content ? (
        <pre className="mt-4 max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-4 font-sans text-sm leading-relaxed text-slate-800">
          {section.draft_content}
        </pre>
      ) : (
        <p className="mt-4 text-sm text-slate-500" role="status">
          Redactando la primera versión…
        </p>
      )}
      {section.evaluation ? <EvaluationSummary evaluation={section.evaluation} /> : null}
    </section>
  );
}

interface EvaluationSummaryProps {
  evaluation: RfpEvaluationResult;
}

function EvaluationSummary({ evaluation }: EvaluationSummaryProps) {
  const { readability, relevance, compliance } = evaluation;
  const checks = [
    { label: "Legibilidad", pass: readability.pass, detail: readability.details },
    {
      label: "Pertinencia",
      pass: relevance.pass,
      detail: relevance.pass
        ? `Responde a los ${relevance.checked_aspects} aspectos clave de la RFP.`
        : `No responde a: ${relevance.missing_aspects.join("; ")}`,
    },
    {
      label: "Cumplimiento",
      pass: compliance.pass,
      detail: compliance.pass
        ? `Cumple los ${compliance.checked_rule_ids.length} lineamientos de la empresa.`
        : compliance.rule_ids.map((ruleId) => rfpComplianceRuleLabels[ruleId] ?? ruleId).join("; "),
    },
  ];
  const violations = compliance.violations.map((violation) => {
    const rule = rfpComplianceRuleLabels[violation.rule_id] ?? violation.rule_id;
    return violation.evidence ? `${rule}: ${violation.detail} «${violation.evidence}»` : `${rule}: ${violation.detail}`;
  });
  return (
    <div className="mt-4">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Evaluación de la iteración {evaluation.iteration}
      </h4>
      <ul className="mt-1.5 space-y-1 text-sm">
        {checks.map((check) => (
          <li key={check.label} className={check.pass ? "text-emerald-800" : "text-amber-800"}>
            <span className="font-semibold">
              {check.pass ? "✓" : "✗"} {check.label}:
            </span>{" "}
            {check.detail}
          </li>
        ))}
      </ul>
      <TextList title="Incumplimientos detectados" items={violations} tone="warning" />
    </div>
  );
}

interface TextListProps {
  title: string;
  items: string[];
  tone?: "default" | "warning";
}

function TextList({ title, items, tone = "default" }: TextListProps) {
  if (items.length === 0) return null;
  return (
    <div className="mt-4">
      <h4 className={`text-xs font-semibold uppercase tracking-wide ${tone === "warning" ? "text-amber-700" : "text-slate-500"}`}>
        {title}
      </h4>
      <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-slate-800">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat("es-ES", { style: "percent", maximumFractionDigits: 0 }).format(value);
}

function formatScore(value: number | null): string {
  return value === null ? "—" : new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(value);
}
