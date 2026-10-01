import {
  clientName,
  formatKpi,
  kpiValue,
  reportingWarehouseLabels,
  weeklyKpis,
  type WeeklyKpi,
  type WeeklyPerformanceEntry,
} from "@/lib/reporting";

interface KpiBarChartProps {
  kpi: WeeklyKpi;
  entries: WeeklyPerformanceEntry[];
}

/** Un KPI por almacén y cliente, de mayor a menor, con barras proporcionales al mayor valor. */
export function KpiBarChart({ kpi, entries }: KpiBarChartProps) {
  const { label, unit } = weeklyKpis[kpi];
  const bars = entries
    .map((entry) => ({
      key: `${entry.warehouse}-${entry.client_id}`,
      warehouse: reportingWarehouseLabels[entry.warehouse],
      client: clientName(entry.client_id),
      value: kpiValue(entry, kpi),
    }))
    .sort((a, b) => b.value - a.value);
  const max = Math.max(...bars.map((bar) => bar.value), 0);

  return (
    <ul className="space-y-3" aria-label={`${label} por almacén y cliente`}>
      {bars.map((bar) => (
        <li key={bar.key} className="grid grid-cols-[minmax(0,11rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="min-w-0">
            <span className="block truncate font-medium text-slate-900" title={bar.client}>
              {bar.client}
            </span>
            <span className="block text-xs text-slate-500">{bar.warehouse}</span>
          </span>
          <span className="h-3 rounded bg-slate-100" aria-hidden="true">
            <span
              className="block h-3 rounded bg-cyan-600"
              style={{ width: max > 0 ? `${(bar.value / max) * 100}%` : "0%" }}
            />
          </span>
          <span className="whitespace-nowrap text-right font-semibold tabular-nums text-slate-900">
            {formatKpi(kpi, bar.value)}
            {unit ? <span className="ml-1 text-xs font-normal text-slate-500">{unit}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}
