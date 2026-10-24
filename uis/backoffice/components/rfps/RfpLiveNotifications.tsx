import Link from "next/link";
import { Panel } from "@/components/ui/Panel";
import {
  rfpStreamStateLabels,
  type RfpStreamState,
  type RfpStreamStatus,
  type RfpTicketCreatedEvent,
} from "@/lib/rfp-events";
import { formatRfpDate, rfpCountryLabels, rfpServiceLabels } from "@/lib/rfps";

interface RfpLiveNotificationsProps {
  status: RfpStreamStatus;
  tickets: RfpTicketCreatedEvent[];
  onDismiss: (ticketId: string) => void;
}

const stateClasses: Record<RfpStreamState, { pill: string; dot: string }> = {
  connecting: { pill: "bg-slate-100 text-slate-700", dot: "bg-slate-400" },
  open: { pill: "bg-emerald-100 text-emerald-800", dot: "bg-emerald-500" },
  reconnecting: { pill: "bg-amber-100 text-amber-800", dot: "bg-amber-500" },
  closed: { pill: "bg-rose-100 text-rose-800", dot: "bg-rose-500" },
};

function StreamStatusPill({ status }: { status: RfpStreamStatus }) {
  const classes = stateClasses[status.state];
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${classes.pill}`}
    >
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${classes.dot}`} />
      {rfpStreamStateLabels[status.state]}
    </span>
  );
}

export function RfpLiveNotifications({ status, tickets, onDismiss }: RfpLiveNotificationsProps) {
  return (
    <Panel
      id="rfp-live"
      title="RFPs nuevas en tiempo real"
      description="Aparecen solas en cuanto el sistema confirma que el documento es una RFP; no hace falta recargar."
    >
      <div role="status" className="mb-4 flex flex-wrap items-center gap-3 text-sm text-slate-600">
        <StreamStatusPill status={status} />
        {status.state === "reconnecting" && status.retryInMs !== null ? (
          <span>
            Se perdió la conexión. Reintento {status.attempt} en {Math.ceil(status.retryInMs / 1000)} s; las RFPs
            que entren mientras tanto se recuperan al reconectar.
          </span>
        ) : null}
        {status.state === "closed" ? <span>Recarga la página para volver a recibir avisos.</span> : null}
      </div>

      <div aria-live="polite">
        {tickets.length === 0 ? (
          <p className="text-sm text-slate-500">Sin RFPs nuevas desde que abriste esta página.</p>
        ) : (
          <ul className="space-y-3">
            {tickets.map((ticket) => (
              <li
                key={ticket.ticket_id}
                className="rounded-lg border border-cyan-300 border-l-4 border-l-cyan-600 bg-cyan-50 p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-wide text-cyan-800">
                      Nueva RFP · requiere procesamiento
                    </p>
                    <p className="mt-1 font-semibold text-slate-950">
                      {ticket.client_name ?? ticket.original_filename}
                    </p>
                    <p className="mt-1 text-sm text-slate-700">
                      {ticket.client_country ? `${rfpCountryLabels[ticket.client_country]} · ` : ""}
                      {ticket.services_requested.length > 0
                        ? ticket.services_requested.map((service) => rfpServiceLabels[service]).join(", ")
                        : "Servicios por confirmar"}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Ticket {ticket.ticket_id} · recibida {formatRfpDate(ticket.created_at)}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <Link
                      href={`/rfps/${ticket.ticket_id}`}
                      className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-slate-800"
                    >
                      Abrir ticket
                    </Link>
                    <button
                      type="button"
                      onClick={() => onDismiss(ticket.ticket_id)}
                      className="text-sm font-medium text-slate-600 underline hover:text-slate-900"
                    >
                      Marcar como vista
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
