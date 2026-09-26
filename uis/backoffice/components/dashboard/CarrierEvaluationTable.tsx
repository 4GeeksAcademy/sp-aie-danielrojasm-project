import { Badge } from "@/components/ui/Panel";
import type { CarrierEvaluation } from "@/lib/carrier-evaluation";
import { formatUSD } from "@/lib/labels";

interface CarrierEvaluationTableProps {
  rows: CarrierEvaluation[];
}

export function CarrierEvaluationTable({ rows }: CarrierEvaluationTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="py-2 pr-3 font-medium">Transportista</th>
            <th scope="col" className="py-2 pr-3 font-medium">Puntuación</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">Coste</th>
            <th scope="col" className="py-2 font-medium">Resultado</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr key={row.carrier.id} className={row.isBest ? "bg-emerald-50" : undefined}>
              <td className="py-2 pr-3 font-medium text-slate-900">{row.carrier.name}</td>
              <td className="py-2 pr-3">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                    <div
                      className={`h-full rounded-full ${row.suitable ? "bg-cyan-600" : "bg-slate-400"}`}
                      style={{ width: `${Math.min(row.score, 100)}%` }}
                    />
                  </div>
                  <span className="tabular-nums">{row.score.toFixed(2)}</span>
                </div>
              </td>
              <td className="py-2 pr-3 text-right tabular-nums">{formatUSD(row.cost)}</td>
              <td className="py-2">
                {row.isBest ? (
                  <Badge tone="success">Recomendado</Badge>
                ) : row.suitable ? (
                  <Badge tone="info">Apto</Badge>
                ) : (
                  <Badge tone="neutral">No apto (&lt; 50)</Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
