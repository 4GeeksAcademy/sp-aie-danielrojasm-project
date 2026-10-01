"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { TelemetryBarList } from "@/components/telemetry/TelemetryBarList";
import { Badge, Panel } from "@/components/ui/Panel";
import {
  errorKindLabels,
  formatRate,
  formatUtc,
  getTelemetryReport,
  rateVital,
  serviceLabels,
  type ReportRange,
  type TelemetryReport,
  type VitalRating,
} from "@/lib/telemetry-report";
import { useApiList } from "@/lib/use-api-list";

const DEFAULT_RANGE: ReportRange = { from: "", to: "" };

const vitalTones: Record<VitalRating, "success" | "warning" | "danger"> = {
  good: "success",
  needs_improvement: "warning",
  poor: "danger",
};

function Vital({ name, value, unit }: { name: Parameters<typeof rateVital>[0]; value: number | null; unit: string }) {
  if (value === null) return <span className="text-slate-400">—</span>;
  return (
    <Badge tone={vitalTones[rateVital(name, value)]}>
      {value.toLocaleString("es-ES")}
      {unit}
    </Badge>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-slate-500">{children}</p>;
}

function Table({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {headers.map((header) => (
              <th key={header} scope="col" className="px-3 py-2">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 tabular-nums">{children}</tbody>
      </table>
    </div>
  );
}

/** Panel a ancho completo en la rejilla de dos columnas (tablas anchas). */
function Wide({ children }: { children: ReactNode }) {
  return <div className="min-w-0 xl:col-span-2">{children}</div>;
}

function ReportSections({ report }: { report: TelemetryReport }) {
  const { events_per_day, events_by_type, error_rate_by_type, page_load_by_route, auth_failure_rate } =
    report.metrics;
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Panel
        id="events-per-day"
        title="Volumen por día y emisor"
        description="Eventos recibidos por día (UTC) y emisor. Un emisor a cero mientras el otro sigue apunta a instrumentación o ingesta rota."
        source="events_per_day"
      >
        {events_per_day.length === 0 ? (
          <Empty>Sin eventos en este período.</Empty>
        ) : (
          <TelemetryBarList
            unit="eventos"
            bars={events_per_day.map((row) => ({
              key: `${row.date}-${row.service}`,
              label: `${row.date} · ${serviceLabels[row.service]}`,
              value: row.events,
              detail: `${row.events} · ${row.sessions} ses.`,
            }))}
          />
        )}
      </Panel>

      <Panel
        id="events-by-type"
        title="Tipos de evento dominantes"
        description="Volumen y peso de cada tipo en el período, con su último registro."
        source="events_by_type"
      >
        {events_by_type.length === 0 ? (
          <Empty>Sin eventos en este período.</Empty>
        ) : (
          <TelemetryBarList
            unit="eventos"
            bars={events_by_type.map((row) => ({
              key: row.event_type,
              label: row.event_type,
              value: row.events,
              detail: `${row.events} · ${formatRate(row.share)}`,
            }))}
          />
        )}
      </Panel>

      <Wide>
        <Panel
          id="error-rate"
          title="Tasa de errores por tipo"
          description="Fallos de cada tipo sobre el total de eventos del día."
          source="error_rate_by_type"
        >
          {error_rate_by_type.length === 0 ? (
            <Empty>Ningún evento de fallo en este período.</Empty>
          ) : (
            <Table headers={["Día", "Evento", "Clase", "Fallos", "Total día", "Tasa"]}>
              {error_rate_by_type.map((row) => (
                <tr key={`${row.date}-${row.event_type}`}>
                  <td className="whitespace-nowrap px-3 py-2">{row.date}</td>
                  <td className="px-3 py-2 font-mono text-xs">{row.event_type}</td>
                  <td className="px-3 py-2">
                    <Badge tone={row.error_kind === "system" ? "danger" : "warning"}>
                      {errorKindLabels[row.error_kind]}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">{row.errors}</td>
                  <td className="px-3 py-2">{row.total_events}</td>
                  <td className="px-3 py-2 font-semibold">{formatRate(row.error_rate)}</td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>
      </Wide>

      <Wide>
        <Panel
          id="auth-failure-rate"
          title="Fallos de login por día"
          description="Intentos fallidos sobre el total de intentos (fallidos + correctos)."
          source="auth_failure_rate"
        >
          {auth_failure_rate.length === 0 ? (
            <Empty>Sin intentos de login en este período.</Empty>
          ) : (
            <Table headers={["Día", "Intentos", "Fallidos", "Correctos", "Tasa de fallo"]}>
              {auth_failure_rate.map((row) => (
                <tr key={row.date}>
                  <td className="whitespace-nowrap px-3 py-2">{row.date}</td>
                  <td className="px-3 py-2">{row.attempts}</td>
                  <td className="px-3 py-2">{row.failed}</td>
                  <td className="px-3 py-2">{row.succeeded}</td>
                  <td className="px-3 py-2 font-semibold">{formatRate(row.failure_rate)}</td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>
      </Wide>

      <Wide>
        <Panel
          id="page-load"
          title="Carga de páginas (p75 de Web Vitals)"
          description="Percentil 75 por ruta y día medido en los navegadores reales. Verde, ámbar y rojo siguen los umbrales oficiales de Web Vitals."
          source="page_load_by_route"
        >
          {page_load_by_route.length === 0 ? (
            <Empty>Sin mediciones de carga en este período.</Empty>
          ) : (
            <Table headers={["Día", "Ruta", "Muestras", "TTFB", "FCP", "LCP", "INP", "CLS"]}>
              {page_load_by_route.map((row) => (
                <tr key={`${row.date}-${row.route}`}>
                  <td className="whitespace-nowrap px-3 py-2">{row.date}</td>
                  <td className="px-3 py-2 font-mono text-xs">{row.route}</td>
                  <td className="px-3 py-2">{row.samples}</td>
                  <td className="px-3 py-2"><Vital name="ttfb_ms_p75" value={row.ttfb_ms_p75} unit=" ms" /></td>
                  <td className="px-3 py-2"><Vital name="fcp_ms_p75" value={row.fcp_ms_p75} unit=" ms" /></td>
                  <td className="px-3 py-2"><Vital name="lcp_ms_p75" value={row.lcp_ms_p75} unit=" ms" /></td>
                  <td className="px-3 py-2"><Vital name="inp_ms_p75" value={row.inp_ms_p75} unit=" ms" /></td>
                  <td className="px-3 py-2"><Vital name="cls_p75" value={row.cls_p75} unit="" /></td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>
      </Wide>
    </div>
  );
}

export function TelemetryReportView() {
  const [range, setRange] = useState<ReportRange>(DEFAULT_RANGE);
  const [draft, setDraft] = useState<ReportRange>(DEFAULT_RANGE);
  // El reporte es un objeto: se reutiliza `useApiList` (carga, error y reintento) con una lista de uno.
  const { items, loading, error, retry } = useApiList<TelemetryReport>(
    async () => [await getTelemetryReport(range)],
    "No se pudo cargar el reporte de telemetría.",
    `${range.from}|${range.to}`,
  );
  const report = items[0];

  const apply = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRange(draft);
  };
  const reset = () => {
    setDraft(DEFAULT_RANGE);
    setRange(DEFAULT_RANGE);
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">
            Ingeniería · Telemetría
          </p>
          <h1 className="mt-2 text-3xl font-bold text-slate-950">Reporte técnico</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Salud del sistema a partir de <code className="font-mono">telemetry_events</code>: volumen,
            errores, latencia de carga y autenticación. Los datos se recalculan como mucho cada 60 s.
          </p>
        </div>
        <form onSubmit={apply} className="flex flex-wrap items-end gap-2 text-xs font-medium text-slate-600">
          <label htmlFor="report-from">
            Desde (UTC)
            <input
              id="report-from"
              type="date"
              value={draft.from}
              max={draft.to || undefined}
              onChange={(event) => setDraft({ ...draft, from: event.target.value })}
              className="mt-1 block rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            />
          </label>
          <label htmlFor="report-to">
            Hasta (incluido)
            <input
              id="report-to"
              type="date"
              value={draft.to}
              min={draft.from || undefined}
              onChange={(event) => setDraft({ ...draft, to: event.target.value })}
              className="mt-1 block rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            />
          </label>
          <button
            type="submit"
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700"
          >
            Aplicar
          </button>
          <button
            type="button"
            onClick={reset}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100"
          >
            Últimos 7 días
          </button>
        </form>
      </header>

      <p className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700" aria-live="polite">
        {loading
          ? "Cargando reporte..."
          : report
            ? (
              <>
                Período: <strong>{formatUtc(report.period.from)}</strong> →{" "}
                <strong>{formatUtc(report.period.to)}</strong>
                <span className="text-slate-500"> · calculado {formatUtc(report.generated_at)}</span>
              </>
            )
            : "Sin datos"}
      </p>

      {loading ? (
        <div aria-busy="true" className="grid gap-6 xl:grid-cols-2">
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className="h-56 animate-pulse rounded-xl bg-slate-100" />
          ))}
        </div>
      ) : null}

      {!loading && error ? <RetryAlert message={error} onRetry={retry} /> : null}

      {!loading && !error && report ? <ReportSections report={report} /> : null}
    </div>
  );
}
