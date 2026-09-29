"use client";

import { useEffect, useState } from "react";
import { Panel } from "@/components/ui/Panel";
import {
  branchLabels,
  fetchIncidentSummary,
  incidentCategoryLabels,
  incidentOriginLabels,
  incidentStatusLabels,
  toFriendlyError,
  type IncidentSummary,
} from "@/lib/incidents";

interface IncidentSummaryPanelProps {
  /** Cambia cuando el listado modifica datos, para recargar las métricas. */
  refreshKey: number;
}

type SummaryState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; summary: IncidentSummary };

interface BreakdownProps<K extends string> {
  title: string;
  counts: Record<K, number>;
  labels: Record<K, string>;
  total: number;
}

function Breakdown<K extends string>({ title, counts, labels, total }: BreakdownProps<K>) {
  const keys = Object.keys(labels) as K[];
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
      <ul className="mt-3 space-y-2">
        {keys.map((key) => {
          const count = counts[key] ?? 0;
          const width = total > 0 ? Math.round((count / total) * 100) : 0;
          return (
            <li key={key} className="text-sm">
              <div className="flex items-baseline justify-between gap-2">
                <span className={count ? "text-slate-700" : "text-slate-400"}>{labels[key]}</span>
                <span className="font-semibold tabular-nums text-slate-900">{count}</span>
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-slate-100" aria-hidden="true">
                <div className="h-1.5 rounded-full bg-cyan-600" style={{ width: `${width}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function IncidentSummaryPanel({ refreshKey }: IncidentSummaryPanelProps) {
  const [state, setState] = useState<SummaryState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    fetchIncidentSummary()
      .then((summary) => {
        if (active) setState({ kind: "ready", summary });
      })
      .catch((error: unknown) => {
        if (active) {
          setState({
            kind: "error",
            message: toFriendlyError(error, "cargar las métricas").message,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [refreshKey, attempt]);

  function retry() {
    setState({ kind: "loading" });
    setAttempt((value) => value + 1);
  }

  return (
    <Panel
      id="resumen-incidencias"
      title="Resumen de incidencias"
      description="Totales por estado, categoría, origen y sede."
    >
      {state.kind === "loading" ? (
        <div aria-busy="true" className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <p className="sr-only" role="status">
            Cargando métricas…
          </p>
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className="h-44 animate-pulse rounded-lg bg-slate-100" />
          ))}
        </div>
      ) : null}

      {state.kind === "error" ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
        >
          <span>{state.message}</span>
          <button
            type="button"
            onClick={retry}
            className="min-h-11 rounded-lg border border-amber-300 bg-white px-4 font-semibold hover:bg-amber-100"
          >
            Reintentar
          </button>
        </div>
      ) : null}

      {state.kind === "ready" ? (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            <span className="text-2xl font-bold tabular-nums text-slate-900">
              {state.summary.total}
            </span>{" "}
            incidencias registradas
          </p>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Breakdown
              title="Por estado"
              counts={state.summary.by_status}
              labels={incidentStatusLabels}
              total={state.summary.total}
            />
            <Breakdown
              title="Por categoría"
              counts={state.summary.by_category}
              labels={incidentCategoryLabels}
              total={state.summary.total}
            />
            <Breakdown
              title="Por origen"
              counts={state.summary.by_origin}
              labels={incidentOriginLabels}
              total={state.summary.total}
            />
            <Breakdown
              title="Por sede"
              counts={state.summary.by_branch}
              labels={branchLabels}
              total={state.summary.total}
            />
          </div>
        </div>
      ) : null}
    </Panel>
  );
}
