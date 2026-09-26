import { Badge } from "@/components/ui/Panel";

export interface ValidationRow {
  entity: "Producto" | "Envío" | "Transportista";
  reference: string;
  valid: boolean;
  errors: string[];
}

interface ValidationReportProps {
  rows: ValidationRow[];
}

export function ValidationReport({ rows }: ValidationReportProps) {
  const invalid = rows.filter((row) => !row.valid);

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        {rows.length - invalid.length} de {rows.length} registros superan las
        reglas de negocio. Los registros con errores se bloquearían antes de
        procesar el pedido.
      </p>
      {invalid.length > 0 ? (
        <ul className="space-y-3">
          {invalid.map((row) => (
            <li
              key={`${row.entity}-${row.reference}`}
              className="rounded-lg border border-rose-200 bg-rose-50 p-3"
            >
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone="danger">{row.entity}</Badge>
                <span className="font-mono text-xs text-slate-700">
                  {row.reference}
                </span>
              </div>
              <ul className="mt-2 list-inside list-disc text-sm text-rose-800">
                {row.errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
