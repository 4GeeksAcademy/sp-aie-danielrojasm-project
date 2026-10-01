"use client";

import { useState, type ReactNode } from "react";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { KpiBarChart } from "@/components/reporting/KpiBarChart";
import { KpiCard, Panel } from "@/components/ui/Panel";
import {
  KPI_ORDER,
  clientName,
  formatKpi,
  formatUpdatedAt,
  formatWeekRange,
  getLatestPipelineRun,
  getWeeklyPerformance,
  kpiValue,
  pipelineRunStatusLabels,
  reportingWarehouseLabels,
  shiftWeek,
  weeklyKpis,
  weeklyTotals,
  type PipelineRun,
  type WeeklyPerformanceReport,
} from "@/lib/reporting";
import { useApiList } from "@/lib/use-api-list";

function Notice({ tone, children }: { tone: "info" | "warning"; children: ReactNode }) {
  const classes = tone === "warning" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-white text-slate-700";
  return <p className={`rounded-lg border px-4 py-3 text-sm ${classes}`}>{children}</p>;
}

function NavButton({ onClick, disabled, children }: { onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function Freshness({ report, run }: { report: WeeklyPerformanceReport; run: PipelineRun | undefined }) {
  return (
    <div className="space-y-2" aria-live="polite">
      <Notice tone="info">
        Semana <strong>{formatWeekRange(report.week_start)}</strong> · lunes a domingo, hora UTC.
        {run?.last_completed_at ? (
          <span className="text-slate-500"> Última actualización del reporte: {formatUpdatedAt(run.last_completed_at)}.</span>
        ) : null}
        {run && (run.status === "pending" || run.status === "running") ? (
          <span className="text-slate-500"> Hay una actualización {pipelineRunStatusLabels[run.status]}.</span>
        ) : null}
      </Notice>
      {run?.stale ? (
        <Notice tone="warning">
          El reporte lleva más de 8 días sin actualizarse: las cifras pueden no estar al día. Avisa al equipo de
          tecnología.
        </Notice>
      ) : null}
      {report.reconciliation_status === "gap" ? (
        <Notice tone="warning">
          Las cifras de esta semana no cuadran del todo con los movimientos registrados en los almacenes: alguna puede
          quedarse corta. Confírmalas con Operaciones antes de tomar una decisión.
        </Notice>
      ) : null}
      {report.reconciliation_status === "unavailable" ? (
        <Notice tone="info">
          Esta semana no se pudo contrastar con los movimientos de los almacenes; las cifras son las que registró el
          sistema.
        </Notice>
      ) : null}
    </div>
  );
}

function DetailTable({ report }: { report: WeeklyPerformanceReport }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="px-3 py-2">Almacén</th>
            <th scope="col" className="px-3 py-2">Cliente</th>
            {KPI_ORDER.map((kpi) => (
              <th key={kpi} scope="col" className="px-3 py-2 text-right">
                {weeklyKpis[kpi].label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 tabular-nums">
          {report.entries.map((entry) => (
            <tr key={`${entry.warehouse}-${entry.client_id}`}>
              <td className="whitespace-nowrap px-3 py-2">{reportingWarehouseLabels[entry.warehouse]}</td>
              <td className="px-3 py-2 font-medium text-slate-900">{clientName(entry.client_id)}</td>
              {KPI_ORDER.map((kpi) => (
                <td key={kpi} className="px-3 py-2 text-right">
                  {formatKpi(kpi, kpiValue(entry, kpi))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportSections({ report }: { report: WeeklyPerformanceReport }) {
  const totals = weeklyTotals(report.entries);
  return (
    <>
      <section aria-labelledby="weekly-totals-title" className="space-y-3">
        <h2 id="weekly-totals-title" className="text-lg font-semibold text-slate-900">
          Total de la semana (Los Ángeles y Zaragoza)
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {KPI_ORDER.map((kpi) => (
            <KpiCard
              key={kpi}
              label={weeklyKpis[kpi].label}
              value={`${formatKpi(kpi, totals[kpi])}${weeklyKpis[kpi].unit ? ` ${weeklyKpis[kpi].unit}` : ""}`}
              hint={weeklyKpis[kpi].question}
            />
          ))}
        </div>
      </section>

      {report.entries.length === 0 ? (
        <Notice tone="info">
          No hubo actividad registrada en ningún almacén esta semana: ni entradas, ni pedidos despachados, ni quiebres
          de stock, ni discrepancias.
        </Notice>
      ) : (
        <>
          <div className="grid gap-6 xl:grid-cols-2">
            {KPI_ORDER.map((kpi) => (
              <Panel
                key={kpi}
                id={`kpi-${kpi}`}
                title={`${weeklyKpis[kpi].label} por almacén y cliente`}
                description={weeklyKpis[kpi].question}
              >
                <KpiBarChart kpi={kpi} entries={report.entries} />
              </Panel>
            ))}
          </div>
          <Panel
            id="weekly-detail"
            title="Detalle por almacén y cliente"
            description="Una fila por cliente en cada almacén; nunca se suman clientes distintos en la misma fila."
          >
            <DetailTable report={report} />
          </Panel>
        </>
      )}
    </>
  );
}

export function WeeklyPerformanceDashboard() {
  // "" = la última semana calculada.
  const [week, setWeek] = useState("");
  const [latestWeek, setLatestWeek] = useState("");
  const { items, loading, error, retry } = useApiList<WeeklyPerformanceReport>(
    async () => {
      const report = await getWeeklyPerformance(week);
      return report ? [report] : [];
    },
    "No se pudo cargar el reporte semanal.",
    week,
  );
  // El estado de la última corrida es un complemento: si falla, el reporte se muestra igual.
  const latestRun = useApiList<PipelineRun>(
    async () => {
      const run = await getLatestPipelineRun();
      return run ? [run] : [];
    },
    "",
  );
  const report = items[0];
  const run = latestRun.error ? undefined : latestRun.items[0];
  if (week === "" && report && report.week_start !== latestWeek) {
    setLatestWeek(report.week_start);
  }
  const shownWeek = report?.week_start ?? week;

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">Dirección · Reporte semanal</p>
          <h1 className="mt-2 text-3xl font-bold text-slate-950">Desempeño por almacén y cliente</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Cuánto recibe y despacha cada almacén para cada cliente, cuántas veces se quedó un producto por debajo de su
            mínimo y qué tan preciso es el inventario. Se actualiza cada lunes con la semana que acaba de cerrar.
          </p>
        </div>
        <nav aria-label="Cambiar de semana" className="flex flex-wrap gap-2">
          <NavButton onClick={() => setWeek(shiftWeek(shownWeek, -1))} disabled={!shownWeek || loading}>
            ← Semana anterior
          </NavButton>
          <NavButton
            onClick={() => setWeek(shiftWeek(shownWeek, 1) === latestWeek ? "" : shiftWeek(shownWeek, 1))}
            disabled={week === "" || loading}
          >
            Semana siguiente →
          </NavButton>
          <NavButton onClick={() => setWeek("")} disabled={week === "" || loading}>
            Última semana
          </NavButton>
        </nav>
      </header>

      {loading ? (
        <div aria-busy="true" className="space-y-6">
          <p className="text-sm text-slate-500">Cargando reporte...</p>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {KPI_ORDER.map((kpi) => (
              <div key={kpi} className="h-32 animate-pulse rounded-xl bg-slate-200" />
            ))}
          </div>
        </div>
      ) : null}

      {!loading && error ? <RetryAlert message={error} onRetry={retry} /> : null}

      {!loading && !error && !report ? (
        <Notice tone="info">
          {week
            ? `La semana ${formatWeekRange(week)} todavía no se ha calculado.`
            : "Todavía no hay ninguna semana calculada. El primer reporte estará disponible el lunes siguiente al cierre de la primera semana con actividad."}
        </Notice>
      ) : null}

      {!loading && !error && report ? (
        <>
          <Freshness report={report} run={run} />
          <ReportSections report={report} />
        </>
      ) : null}
    </div>
  );
}
