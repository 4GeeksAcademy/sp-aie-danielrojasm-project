export interface TelemetryBar {
  key: string;
  label: string;
  value: number;
  /** Texto a la derecha de la barra; por defecto, el valor. */
  detail?: string;
}

interface TelemetryBarListProps {
  bars: TelemetryBar[];
  /** Nombre de la serie para lectores de pantalla (p. ej. «eventos»). */
  unit: string;
}

/** Barras horizontales proporcionales al mayor valor, sin librería de gráficos. */
export function TelemetryBarList({ bars, unit }: TelemetryBarListProps) {
  const max = Math.max(...bars.map((bar) => bar.value), 1);
  return (
    <ul className="space-y-2">
      {bars.map((bar) => (
        <li key={bar.key} className="grid grid-cols-[minmax(0,12rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate font-mono text-xs text-slate-700" title={bar.label}>
            {bar.label}
          </span>
          <span className="h-3 rounded bg-slate-100" aria-hidden="true">
            <span
              className="block h-3 rounded bg-cyan-600"
              style={{ width: `${(bar.value / max) * 100}%` }}
            />
          </span>
          <span className="whitespace-nowrap tabular-nums text-slate-900">
            <span className="sr-only">
              {bar.label}: {bar.value} {unit}
              {bar.detail ? ` (${bar.detail})` : ""}
            </span>
            <span aria-hidden="true">{bar.detail ?? bar.value}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
