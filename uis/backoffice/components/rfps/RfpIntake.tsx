"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { RfpStatusBadge } from "@/components/rfps/RfpStatusBadge";
import { Panel } from "@/components/ui/Panel";
import { getUserMessage } from "@/lib/api-client";
import {
  formatRfpDate,
  isRfpInProgress,
  listRfps,
  rfpCountryLabels,
  rfpDepartmentLabels,
  RFP_POLL_INTERVAL_MS,
  uploadRfp,
  validateRfpFile,
  type RfpTicketCreated,
} from "@/lib/rfps";
import { useApiList } from "@/lib/use-api-list";

const UPLOAD_FALLBACK_ERROR = "No se pudo registrar la RFP. Inténtalo de nuevo.";
const LIST_FALLBACK_ERROR = "No se pudieron cargar las RFPs.";

export function RfpIntake() {
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [created, setCreated] = useState<RfpTicketCreated | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const tickets = useApiList(listRfps, LIST_FALLBACK_ERROR, String(refreshKey));
  const pending = tickets.items.some((ticket) => isRfpInProgress(ticket.status));

  // Mientras haya tickets en análisis o generación, la lista se refresca sola hasta que cambien de estado.
  useEffect(() => {
    if (!pending) return;
    const timer = window.setTimeout(() => setRefreshKey((key) => key + 1), RFP_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [pending, tickets.items]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = validateRfpFile(file);
    setError(validation);
    if (validation || !file || uploading) return;
    setUploading(true);
    setCreated(null);
    try {
      setCreated(await uploadRfp(file));
      setFile(null);
      setFileInputKey((key) => key + 1);
      setRefreshKey((key) => key + 1);
    } catch (caught) {
      setError(getUserMessage(caught, UPLOAD_FALLBACK_ERROR));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">
          Comercial · Propuestas
        </p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">Recepción de RFPs</h1>
        <p className="mt-2 text-sm text-slate-600">
          Sube la RFP del cliente en PDF. Cada archivo crea un ticket: el sistema comprueba si es una RFP,
          extrae sus datos y reparte el análisis entre Almacén, Última milla y Logística inversa según lo que
          pide el cliente.
        </p>
      </header>

      <Panel id="rfp-upload" title="Subir RFP" description="Solo PDF, hasta 10 MB.">
        <form onSubmit={handleSubmit} noValidate className="space-y-4">
          <div>
            <label htmlFor="rfp-file" className="block text-sm font-semibold text-slate-800">
              Documento de la RFP
            </label>
            <input
              key={fileInputKey}
              id="rfp-file"
              name="file"
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) => {
                setFile(event.target.files?.item(0) ?? null);
                setError(null);
              }}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "rfp-file-error" : undefined}
              className="mt-2 block w-full text-sm text-slate-700 file:mr-4 file:rounded-md file:border-0 file:bg-slate-900 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-slate-800"
            />
            {error ? (
              <p id="rfp-file-error" role="alert" className="mt-1.5 text-sm font-medium text-rose-700">
                {error}
              </p>
            ) : null}
          </div>
          <button
            type="submit"
            disabled={uploading}
            className="rounded-md bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-wait disabled:opacity-60"
          >
            {uploading ? "Subiendo…" : "Crear ticket"}
          </button>
        </form>
        <div aria-live="polite">
          {created ? (
            <p className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
              Ticket creado. El análisis está en curso; el estado se actualiza solo.{" "}
              <Link href={`/rfps/${created.ticket_id}`} className="font-semibold underline">
                Ver el ticket
              </Link>
            </p>
          ) : null}
        </div>
      </Panel>

      <Panel id="rfp-tickets" title="Tickets de RFP" description="Los más recientes primero.">
        {tickets.error ? (
          <RetryAlert message={tickets.error} onRetry={tickets.retry} />
        ) : tickets.loading && tickets.items.length === 0 ? (
          <p className="text-sm text-slate-500" role="status">
            Cargando tickets…
          </p>
        ) : tickets.items.length === 0 ? (
          <p className="text-sm text-slate-500">Todavía no se ha subido ninguna RFP.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <caption className="sr-only">Tickets de RFP y su estado</caption>
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="py-2 pr-4">Archivo</th>
                  <th scope="col" className="py-2 pr-4">Cliente</th>
                  <th scope="col" className="py-2 pr-4">Departamentos</th>
                  <th scope="col" className="py-2 pr-4">Estado</th>
                  <th scope="col" className="py-2">Recibida</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {tickets.items.map((ticket) => (
                  <tr key={ticket.ticket_id}>
                    <td className="py-3 pr-4">
                      <Link href={`/rfps/${ticket.ticket_id}`} className="font-medium text-cyan-800 hover:underline">
                        {ticket.original_filename}
                      </Link>
                    </td>
                    <td className="py-3 pr-4 text-slate-700">
                      {ticket.client_name ?? "—"}
                      {ticket.client_country ? (
                        <span className="block text-xs text-slate-500">{rfpCountryLabels[ticket.client_country]}</span>
                      ) : null}
                    </td>
                    <td className="py-3 pr-4 text-slate-700">
                      {ticket.departments_needed.length > 0
                        ? ticket.departments_needed.map((id) => rfpDepartmentLabels[id]).join(", ")
                        : "—"}
                    </td>
                    <td className="py-3 pr-4">
                      <RfpStatusBadge status={ticket.status} hasError={Boolean(ticket.last_error)} />
                    </td>
                    <td className="py-3 text-slate-600">{formatRfpDate(ticket.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
