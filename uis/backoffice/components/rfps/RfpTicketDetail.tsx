"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { RfpApprovalForm } from "@/components/rfps/RfpApprovalForm";
import { RfpFinalDocument } from "@/components/rfps/RfpFinalDocument";
import { RfpApprovalStatusBadge, RfpSectionStatusBadge, RfpStatusBadge } from "@/components/rfps/RfpStatusBadge";
import { RfpTracePanel } from "@/components/rfps/RfpTracePanel";
import { Panel } from "@/components/ui/Panel";
import { getUserMessage } from "@/lib/api-client";
import {
  formatDeadline,
  formatRfpDate,
  getRfp,
  isRfpInProgress,
  isRfpOpeningApproval,
  rfpArbitrationActionLabels,
  rfpComplianceRuleLabels,
  rfpCountryLabels,
  rfpDecisionLabels,
  rfpDepartmentLabels,
  RFP_POLL_INTERVAL_MS,
  rfpServiceLabels,
  rfpTriggerLabels,
  type RfpArbitration,
  type RfpDepartmentId,
  type RfpDepartmentSection,
  type RfpEvaluationResult,
  type RfpMetadata,
  type RfpTicket,
} from "@/lib/rfps";

const LOAD_FALLBACK_ERROR = "No se pudo cargar la RFP.";

/** Ronda de revisión cuya decisión ya se envió, por departamento (mientras el worker la aplica). */
type SubmittedRounds = Partial<Record<RfpDepartmentId, number>>;

interface RfpTicketDetailProps {
  ticketId: string;
}

export function RfpTicketDetail({ ticketId }: RfpTicketDetailProps) {
  const [ticket, setTicket] = useState<RfpTicket | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [submitted, setSubmitted] = useState<SubmittedRounds>({});

  // Carga inicial y consulta periódica mientras el worker trabaja o algún responsable tiene que decidir.
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const load = async () => {
      try {
        const loaded = await getRfp(ticketId);
        if (!active) return;
        setTicket(loaded);
        setError("");
        if (isRfpInProgress(loaded.status) || loaded.status === "esperando_aprobación") {
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
      {ticket ? (
        <TicketView
          ticket={ticket}
          submitted={submitted}
          onDecisionSubmitted={(departmentId, round) => {
            setSubmitted((current) => ({ ...current, [departmentId]: round }));
            setAttempt((value) => value + 1);
          }}
        />
      ) : null}
    </div>
  );
}

interface TicketViewProps {
  ticket: RfpTicket;
  submitted: SubmittedRounds;
  onDecisionSubmitted: (departmentId: RfpDepartmentId, round: number) => void;
}

function TicketView({ ticket, submitted, onDecisionSubmitted }: TicketViewProps) {
  const analyzed = ticket.status !== "analizando" && ticket.status !== "descartado";
  const openingApproval = isRfpOpeningApproval(ticket.status, ticket.response_handoff_ready);
  const generating = analyzed && isRfpInProgress(ticket.status) && !openingApproval;
  const drafts = ticket.sections.filter((section) => section.draft_status !== null);
  const provisional = drafts.filter((section) => section.draft_status === "needs_human_review");
  const awaiting = ticket.sections.filter((section) => section.approval_status === "pendiente");
  const rejected = ticket.sections.filter((section) => section.approval_status === "rechazada");
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
        {openingApproval ? (
          <p className="rounded-lg border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-900" role="status">
            Borradores listos: se está abriendo la revisión de cada responsable (y el arbitraje, si dos secciones se
            contradicen). Esta página se actualiza sola.
          </p>
        ) : null}
        {ticket.status === "esperando_aprobación" && awaiting.length > 0 ? (
          <p className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900" role="status">
            Esperando la decisión de{" "}
            {awaiting
              .map((section) => `${section.responsible} (${rfpDepartmentLabels[section.department_id]})`)
              .join(", ")}
            . Cada responsable decide su sección sin esperar a los demás; el documento final se genera solo cuando
            todas están aprobadas.
          </p>
        ) : null}
        {ticket.status === "esperando_aprobación" && awaiting.length === 0 && rejected.length === 0 ? (
          <p className="rounded-lg border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-900" role="status">
            Aplicando la última decisión registrada. Esta página se actualiza sola.
          </p>
        ) : null}
        {rejected.length > 0 ? (
          <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            <p className="font-semibold">
              {rejected.map((section) => rfpDepartmentLabels[section.department_id]).join(", ")}:{" "}
              {rejected.length === 1 ? "sección rechazada" : "secciones rechazadas"}. No se generará el documento
              final de esta ejecución.
            </p>
            <p className="mt-1">
              Para volver a intentarlo hace falta una ejecución nueva: avisa al equipo técnico con el ticket{" "}
              {ticket.ticket_id}.
            </p>
          </div>
        ) : null}
        {ticket.status === "terminado" ? (
          <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900" role="status">
            Todas las secciones están aprobadas por su responsable y el documento final está listo para enviar.
          </p>
        ) : null}
        {ticket.last_error ? (
          <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <p className="font-semibold">
              {failureMessage(ticket)} Se reintenta automáticamente; si no avanza, avisa al equipo técnico con el
              ticket {ticket.ticket_id}.
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
          {ticket.final_document_ready ? (
            <RfpFinalDocument ticketId={ticket.ticket_id} clientName={ticket.metadata.client_name} />
          ) : null}
          {ticket.arbitrations.length > 0 ? <ArbitrationPanel arbitrations={ticket.arbitrations} /> : null}
          {drafts.length > 0 ? (
            <section aria-labelledby="rfp-drafts-title" className="space-y-4">
              <h2 id="rfp-drafts-title" className="text-lg font-semibold text-slate-900">
                Borrador de la propuesta económica
              </h2>
              {drafts.map((section) => (
                <DraftCard
                  key={section.department_id}
                  ticketId={ticket.ticket_id}
                  section={section}
                  submittedRound={submitted[section.department_id]}
                  onDecisionSubmitted={onDecisionSubmitted}
                />
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
      <RfpTracePanel ticketId={ticket.ticket_id} trace={ticket.trace} />
    </>
  );
}

function failureMessage(ticket: RfpTicket): string {
  if (ticket.status === "analizando") return `El análisis falló en el intento ${ticket.attempts}.`;
  if (!ticket.response_handoff_ready) {
    return `La generación de borradores falló en el intento ${ticket.generation_attempts}.`;
  }
  return "La aprobación no pudo avanzar (apertura de la revisión o aplicación de una decisión).";
}

interface ArbitrationPanelProps {
  arbitrations: RfpArbitration[];
}

function ArbitrationPanel({ arbitrations }: ArbitrationPanelProps) {
  return (
    <Panel
      id="rfp-arbitrations"
      title="Arbitraje entre departamentos"
      description="Contradicciones detectadas en código y resueltas con el árbitro y la regla fijos del BRIEFING."
    >
      <ul className="space-y-3 text-sm text-slate-800">
        {arbitrations.map((record) => (
          <li key={`${record.round}-${record.trigger_id}-${record.department_id}`}>
            <p className="font-semibold">
              Ronda {record.round} · {rfpTriggerLabels[record.trigger_id]} · {rfpDepartmentLabels[record.department_id]}
              : {rfpArbitrationActionLabels[record.action]}
            </p>
            <p>
              Árbitro: {record.arbiter}. {record.rule}
            </p>
            <p className="text-slate-600">Evidencia: {record.evidence}</p>
          </li>
        ))}
      </ul>
    </Panel>
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
  ticketId: string;
  section: RfpDepartmentSection;
  submittedRound: number | undefined;
  onDecisionSubmitted: (departmentId: RfpDepartmentId, round: number) => void;
}

function DraftCard({ ticketId, section, submittedRound, onDecisionSubmitted }: DraftCardProps) {
  const headingId = `rfp-draft-${section.department_id}`;
  const provisional = section.draft_status === "needs_human_review";
  const review = section.pending_review;
  const awaitingWorker = review !== null && submittedRound === review.review_round;
  return (
    <section
      aria-labelledby={headingId}
      className={`rounded-xl border bg-white p-5 shadow-sm ${provisional ? "border-amber-300" : "border-slate-200"}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={headingId} className="text-base font-semibold text-slate-900">
          {rfpDepartmentLabels[section.department_id]}
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          {section.approval_status ? <RfpApprovalStatusBadge status={section.approval_status} /> : null}
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
      {section.approver && section.approved_at ? (
        <p className="mt-4 text-sm text-emerald-800">
          Aprobada por {section.approver} el {formatRfpDate(section.approved_at)} (revisión {section.review_round}).
        </p>
      ) : null}
      {review && !awaitingWorker ? (
        <RfpApprovalForm
          ticketId={ticketId}
          departmentId={section.department_id}
          review={review}
          onSubmitted={() => onDecisionSubmitted(section.department_id, review.review_round)}
        />
      ) : null}
      {awaitingWorker ? (
        <p className="mt-4 text-sm text-cyan-900" role="status">
          Decisión registrada: se está aplicando. Esta página se actualiza sola.
        </p>
      ) : null}
      <TextList
        title="Historial de decisiones"
        items={section.approval_history.map(
          (entry) =>
            `Revisión ${entry.review_round} · ${rfpDecisionLabels[entry.decision]} (${entry.approver}, registrada por ${entry.decided_by} el ${formatRfpDate(entry.decided_at)})${entry.comment ? `: ${entry.comment}` : ""}`,
        )}
      />
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
