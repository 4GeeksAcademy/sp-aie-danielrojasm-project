"use client";

import { useEffect, useEffectEvent, useState } from "react";
import {
  RfpTicketStream,
  type RfpStreamStatus,
  type RfpTicketCreatedEvent,
} from "@/lib/rfp-events";

export interface RfpTicketStreamState {
  status: RfpStreamStatus;
  /** RFPs notificadas desde que se abrió la vista, la más reciente primero y sin repetir `ticket_id`. */
  tickets: RfpTicketCreatedEvent[];
}

/**
 * Abre el stream de RFPs nuevas mientras el componente está montado. Si el
 * navegador vuelve a tener red, reintenta sin esperar al backoff.
 *
 * @param onReconnected Tras recuperar la conexión (p. ej. para refrescar estados).
 */
export function useRfpTicketStream(onReconnected: () => void): RfpTicketStreamState {
  const [status, setStatus] = useState<RfpStreamStatus>({
    state: "connecting",
    attempt: 0,
    retryInMs: null,
  });
  const [tickets, setTickets] = useState<RfpTicketCreatedEvent[]>([]);
  const handleReconnected = useEffectEvent(onReconnected);

  useEffect(() => {
    const stream = new RfpTicketStream({
      onTicket: (event) =>
        setTickets((current) =>
          current.some((ticket) => ticket.ticket_id === event.ticket_id) ? current : [event, ...current],
        ),
      onStatus: setStatus,
      onReconnected: () => handleReconnected(),
    });
    const goOnline = () => stream.retryNow();
    const goOffline = () => stream.dropConnection();
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    stream.start();
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      stream.stop();
    };
  }, []);

  return { status, tickets };
}
