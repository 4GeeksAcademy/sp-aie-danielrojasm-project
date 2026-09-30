"use client";

import { KpiCard, Panel } from "@/components/ui/Panel";
import {
  INCIDENT_CATEGORY_LABELS,
  INCIDENT_STATUS_LABELS,
  INVALID_REASON_LABELS,
  type IncidentAnalysisSummary,
  type IncidentCategory,
  type IncidentStatus,
} from "@/lib/incident-analysis";

const SATISFACTION_LABELS = [
  "Muy insatisfecho",
  "Insatisfecho",
  "Neutral",
  "Satisfecho",
  "Muy satisfecho",
];

const EMPTY_BREAKDOWN = { count: 0, percentage: 0 };

interface IncidentAnalysisResultsProps {
  summary: IncidentAnalysisSummary;
  onExport: () => void;
  isExporting: boolean;
  exportError: string | null;
}

/**
 * Resultados del análisis CSV. Solo existen tras un análisis correcto, así que
 * `IncidentAnalysis` los carga con `next/dynamic`: quien abre la vista y no
 * sube ningún fichero no descarga este código.
 */
export function IncidentAnalysisResults({
  summary,
  onExport,
  isExporting,
  exportError,
}: IncidentAnalysisResultsProps) {
  return (
    <>
      <section aria-labelledby="incident-summary-title" className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="incident-summary-title" className="text-lg font-semibold">
              Resumen del análisis
            </h2>
            <p className="text-sm text-slate-500">
              Métricas calculadas solo sobre registros válidos.
            </p>
          </div>
          <button
            type="button"
            onClick={onExport}
            disabled={isExporting}
            className="min-h-10 border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50 disabled:cursor-wait disabled:opacity-60"
          >
            {isExporting ? "Preparando CSV…" : "Descargar resultados CSV"}
          </button>
        </div>
        {exportError ? (
          <div role="alert" className="flex flex-wrap items-center gap-3 text-sm font-medium text-rose-700">
            <span>{exportError}</span>
            <button
              type="button"
              onClick={onExport}
              disabled={isExporting}
              className="min-h-9 border border-rose-300 bg-white px-3 font-semibold text-rose-800 hover:bg-rose-50"
            >
              Reintentar descarga
            </button>
          </div>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            label="Registros totales"
            value={String(summary.total_records ?? 0)}
            hint="Filas procesadas"
          />
          <KpiCard
            label="Registros válidos"
            value={String(summary.valid_records ?? 0)}
            hint="Incluidos en los desgloses"
          />
          <KpiCard
            label="Registros inválidos"
            value={String(summary.invalid_records ?? 0)}
            hint="Excluidos de las métricas"
            tone={(summary.invalid_records ?? 0) > 0 ? "warning" : "default"}
          />
          <KpiCard
            label="Satisfacción media"
            value={
              typeof summary.average_satisfaction !== "number"
                ? "N/D"
                : `${summary.average_satisfaction.toFixed(2)} / 5`
            }
            hint={`${summary.scored_closed_incidents ?? 0} casos cerrados con puntuación`}
          />
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Incidencias por categoría">
          <ul className="space-y-4">
            {(Object.keys(INCIDENT_CATEGORY_LABELS) as IncidentCategory[]).map(
              (category) => {
                const value = summary.categories?.[category] ?? EMPTY_BREAKDOWN;
                return (
                  <li key={category}>
                    <div className="flex justify-between gap-3 text-sm">
                      <span className="font-medium">
                        {INCIDENT_CATEGORY_LABELS[category]}
                        <span className="ml-2 font-mono text-xs text-slate-500">
                          {category}
                        </span>
                      </span>
                      <span className="shrink-0 tabular-nums text-slate-600">
                        {value.count} · {value.percentage.toFixed(1)}%
                      </span>
                    </div>
                    <div
                      className="mt-2 h-2 bg-slate-100"
                      role="img"
                      aria-label={`${value.percentage.toFixed(1)} por ciento`}
                    >
                      <div
                        className="h-full bg-cyan-700"
                        style={{ width: `${value.percentage}%` }}
                      />
                    </div>
                  </li>
                );
              },
            )}
          </ul>
        </Panel>

        <Panel title="Incidencias por estado">
          <dl className="divide-y divide-slate-100">
            {(Object.keys(INCIDENT_STATUS_LABELS) as IncidentStatus[]).map(
              (status) => (
                <div
                  key={status}
                  className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                >
                  <dt>
                    <span className="block text-sm font-medium">
                      {INCIDENT_STATUS_LABELS[status]}
                    </span>
                    <span className="font-mono text-xs text-slate-500">
                      {status}
                    </span>
                  </dt>
                  <dd className="text-right tabular-nums">
                    <span className="block font-semibold">
                      {summary.statuses?.[status]?.count ?? 0}
                    </span>
                    <span className="text-xs text-slate-500">
                      {(summary.statuses?.[status]?.percentage ?? 0).toFixed(1)}%
                    </span>
                  </dd>
                </div>
              ),
            )}
          </dl>
        </Panel>

        <Panel title="Puntuaciones en casos cerrados">
          <p className="mb-4 text-sm text-slate-600">
            {summary.scored_closed_incidents ?? 0} de {summary.closed_incidents ?? 0} casos
            cerrados tienen puntuación registrada.
          </p>
          <ol className="divide-y divide-slate-100">
            {SATISFACTION_LABELS.map((label, index) => {
              const score = String(index + 1) as "1" | "2" | "3" | "4" | "5";
              return (
                <li
                  key={score}
                  className="flex justify-between gap-3 py-2 text-sm first:pt-0 last:pb-0"
                >
                  <span>
                    <span className="mr-2 font-semibold tabular-nums">{score}</span>
                    {label}
                  </span>
                  <span className="tabular-nums text-slate-600">
                    {summary.satisfaction_scores?.[score] ?? 0}
                  </span>
                </li>
              );
            })}
          </ol>
        </Panel>

        <Panel title="Incidencias por país">
          <dl className="divide-y divide-slate-100">
            {(["US", "ES"] as const).map((country) => {
              const value = summary.countries?.[country] ?? EMPTY_BREAKDOWN;
              return (
              <div
                key={country}
                className="flex justify-between gap-4 py-3 text-sm first:pt-0 last:pb-0"
              >
                <dt className="font-medium">{country}</dt>
                <dd className="tabular-nums text-slate-600">
                  {value.count} · {value.percentage.toFixed(1)}%
                </dd>
              </div>
              );
            })}
          </dl>
        </Panel>
      </div>

      <Panel title="Calidad de los registros">
        {(summary.invalid_records ?? 0) === 0 ? (
          <p className="text-sm font-medium text-emerald-800">
            No se detectaron registros inválidos.
          </p>
        ) : (
          <div>
            <p className="mb-3 text-sm text-slate-700">
              {summary.invalid_records} registros se excluyeron del análisis.
              Un mismo registro puede activar más de una regla.
            </p>
            <ul className="grid gap-x-8 sm:grid-cols-2">
              {Object.entries(summary.invalid_breakdown ?? {})
                .filter(([, value]) => value.count > 0)
                .map(([key, value]) => (
                  <li
                    key={key}
                    className="flex justify-between gap-3 border-t border-slate-100 py-2 text-sm"
                  >
                    <span>{INVALID_REASON_LABELS[key] ?? value.label}</span>
                    <span className="shrink-0 font-semibold tabular-nums">
                      {value.count}
                    </span>
                  </li>
                ))}
            </ul>
          </div>
        )}
      </Panel>
    </>
  );
}
