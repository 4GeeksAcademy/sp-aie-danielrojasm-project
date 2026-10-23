import { Panel } from "@/components/ui/Panel";
import { formatRfpDate, rfpDepartmentLabels, rfpTracePartLabels, type RfpDepartmentId, type RfpTraceEntry } from "@/lib/rfps";

interface RfpTracePanelProps {
  ticketId: string;
  trace: RfpTraceEntry[];
}

/** Qué agente hizo qué y en qué orden, en las tres partes: el registro para dar soporte a un ticket. */
export function RfpTracePanel({ ticketId, trace }: RfpTracePanelProps) {
  if (trace.length === 0) return null;
  return (
    <Panel
      id="rfp-trace"
      title="Traza de la ejecución"
      description={`${trace.length} pasos registrados con su agente, entrada, salida y hora (ticket ${ticketId}).`}
    >
      <details>
        <summary className="cursor-pointer text-sm font-medium text-cyan-800">Ver los pasos en orden</summary>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="py-2 pr-4">Hora</th>
                <th scope="col" className="py-2 pr-4">Parte</th>
                <th scope="col" className="py-2 pr-4">Paso</th>
                <th scope="col" className="py-2 pr-4">Agente</th>
                <th scope="col" className="py-2 pr-4">Departamento</th>
                <th scope="col" className="py-2">Salida</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-800">
              {trace.map((entry, index) => (
                <tr key={`${entry.timestamp}-${entry.node}-${index}`} className="align-top">
                  <td className="whitespace-nowrap py-2 pr-4">{formatRfpDate(entry.timestamp)}</td>
                  <td className="py-2 pr-4">{rfpTracePartLabels[entry.part]}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{entry.node}</td>
                  <td className="py-2 pr-4">{entry.agent}</td>
                  <td className="py-2 pr-4">{departmentLabel(entry.department_id)}</td>
                  <td className="py-2">
                    <details>
                      <summary className="cursor-pointer text-xs text-cyan-800">Entrada y salida</summary>
                      <pre className="mt-1 max-h-60 max-w-xl overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">
                        {JSON.stringify({ entrada: entry.input, salida: entry.output }, null, 2)}
                      </pre>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </Panel>
  );
}

function departmentLabel(departmentId: string | null): string {
  if (!departmentId) return "—";
  return rfpDepartmentLabels[departmentId as RfpDepartmentId] ?? departmentId;
}
