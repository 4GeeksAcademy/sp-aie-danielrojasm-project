"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { RfpStatusBadge } from "@/components/rfps/RfpStatusBadge";
import { Panel } from "@/components/ui/Panel";
import { getUserMessage } from "@/lib/api-client";
import {
  formatDeadline,
  formatRfpDate,
  getRfp,
  rfpCountryLabels,
  rfpDepartmentLabels,
  RFP_POLL_INTERVAL_MS,
  rfpServiceLabels,
  type RfpDepartmentSection,
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

  // Carga inicial y consulta periódica mientras el análisis sigue en curso.
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const load = async () => {
      try {
        const loaded = await getRfp(ticketId);
        if (!active) return;
        setTicket(loaded);
        setError("");
        if (loaded.status === "analizando") timer = window.setTimeout(load, RFP_POLL_INTERVAL_MS);
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
        {ticket.last_error ? (
          <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <p className="font-semibold">
              El análisis falló en el intento {ticket.attempts}. Se reintenta automáticamente; si no avanza, avisa
              al equipo técnico con el ticket {ticket.ticket_id}.
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

      {ticket.status === "analisis_completo" && ticket.metadata ? (
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
          {ticket.handoff_ready ? (
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
