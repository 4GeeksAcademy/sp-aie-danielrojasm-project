/**
 * Notificación en tiempo real de RFPs nuevas: cliente de `GET /rfps/events` (SSE).
 *
 * Se usa `fetch` + `ReadableStream` y no `EventSource`, porque el stream exige el
 * mismo JWT que el resto del backoffice (`Authorization: Bearer`, vía `apiFetch`).
 *
 * - Reconexión con backoff exponencial (1 s, 2 s, 4 s… hasta 30 s, con jitter) si
 *   la conexión se corta, la API responde 5xx o no llega nada (ni el `: ping` de
 *   keep-alive) en `RFP_STREAM_STALE_MS`.
 * - Recuperación: cada evento trae `id:`; al reconectar se envía el último en
 *   `Last-Event-ID` y la API reenvía las RFPs que entraron mientras tanto.
 * - Deduplicación por `ticket_id`: un ticket reenviado no vuelve a notificarse.
 */
import { apiFetch } from "@/lib/api-client";
import type { RfpClientCountry, RfpService, RfpTicketListItem } from "@/lib/rfps";

const RFP_EVENTS_API = "/api/rfps/events";

export const RFP_TICKET_CREATED = "rfp_ticket_created";
export const RFP_RECONNECT_BASE_MS = 1000;
export const RFP_RECONNECT_MAX_MS = 30_000;
/** La API manda un `: ping` cada 15 s; sin nada en 45 s, la conexión está muerta. */
export const RFP_STREAM_STALE_MS = 45_000;

/** `data:` del evento `rfp_ticket_created` (mismos campos que el ticket en la API). */
export interface RfpTicketCreatedEvent {
  ticket_id: string;
  rfp_id: string;
  client_name: string | null;
  client_country: RfpClientCountry | null;
  services_requested: RfpService[];
  status: "analizando";
  original_filename: string;
  created_at: string;
}

export type RfpStreamState = "connecting" | "open" | "reconnecting" | "closed";

export interface RfpStreamStatus {
  state: RfpStreamState;
  /** Intentos de reconexión seguidos sin éxito. */
  attempt: number;
  /** Espera hasta el siguiente intento, en `reconnecting`. */
  retryInMs: number | null;
}

export const rfpStreamStateLabels: Record<RfpStreamState, string> = {
  connecting: "Conectando…",
  open: "En vivo",
  reconnecting: "Sin conexión · reintentando",
  closed: "Notificaciones detenidas",
};

export interface SseMessage {
  id: string | null;
  event: string;
  data: string;
}

/**
 * Parser incremental del formato `text/event-stream`: recibe trozos de texto
 * tal como llegan de la red y devuelve los mensajes completos. Los comentarios
 * (`: ping`) no generan mensaje.
 */
export function createSseParser(): (chunk: string) => SseMessage[] {
  let buffer = "";
  return (chunk) => {
    buffer += chunk;
    const blocks = buffer.split(/\r\n\r\n|\n\n|\r\r/);
    buffer = blocks.pop() ?? "";
    const messages: SseMessage[] = [];
    for (const block of blocks) {
      let id: string | null = null;
      let event = "message";
      const data: string[] = [];
      for (const line of block.split(/\r\n|\n|\r/)) {
        if (line === "" || line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "id") id = value;
        else if (field === "event") event = value;
        else if (field === "data") data.push(value);
      }
      if (data.length > 0) messages.push({ id, event, data: data.join("\n") });
    }
    return messages;
  };
}

/** Espera antes del intento `attempt` (0, 1, 2…): exponencial con tope y jitter. */
export function reconnectDelayMs(attempt: number, random: () => number = Math.random): number {
  const ceiling = Math.min(RFP_RECONNECT_MAX_MS, RFP_RECONNECT_BASE_MS * 2 ** attempt);
  // La mitad fija y la otra mitad aleatoria: varias pestañas no reconectan a la vez.
  return Math.round(ceiling / 2 + (ceiling / 2) * random());
}

/** Fila de la tabla a partir del evento, sin volver a pedir la lista. */
export function eventToListItem(event: RfpTicketCreatedEvent): RfpTicketListItem {
  return {
    ticket_id: event.ticket_id,
    status: event.status,
    original_filename: event.original_filename,
    client_name: event.client_name,
    client_country: event.client_country,
    departments_needed: [],
    attempts: 0,
    last_error: null,
    response_handoff_ready: false,
    created_at: event.created_at,
    updated_at: event.created_at,
  };
}

/**
 * Lista de la API más las RFPs notificadas que aún no están en ella, sin
 * duplicar ningún `ticket_id`. Si el ticket ya llegó por la API, manda la API
 * (tiene el estado más reciente).
 */
export function mergeLiveTickets(
  items: RfpTicketListItem[],
  live: RfpTicketCreatedEvent[],
): RfpTicketListItem[] {
  const known = new Set(items.map((item) => item.ticket_id));
  const added = live.filter((event) => !known.has(event.ticket_id)).map(eventToListItem);
  return [...added, ...items].sort((a, b) => b.created_at.localeCompare(a.created_at));
}

function isTicketCreatedEvent(value: unknown): value is RfpTicketCreatedEvent {
  if (typeof value !== "object" || value === null) return false;
  const event = value as Partial<RfpTicketCreatedEvent>;
  return (
    typeof event.ticket_id === "string" &&
    typeof event.rfp_id === "string" &&
    typeof event.original_filename === "string" &&
    typeof event.created_at === "string" &&
    Array.isArray(event.services_requested)
  );
}

class StreamClosedError extends Error {
  constructor(readonly status: number) {
    super(`El stream de RFPs respondió ${status}.`);
  }
}

export interface RfpTicketStreamOptions {
  onTicket: (event: RfpTicketCreatedEvent) => void;
  onStatus: (status: RfpStreamStatus) => void;
  /** La conexión se recuperó tras un corte (no se llama en la primera). */
  onReconnected?: () => void;
  /** Inyectables para los tests. */
  fetchStream?: (url: string, init: RequestInit) => Promise<Response>;
  random?: () => number;
  staleAfterMs?: number;
}

/**
 * Conexión al stream con reconexión. `start()` abre el bucle y `stop()` lo
 * cierra para siempre (al desmontar el componente).
 */
export class RfpTicketStream {
  private readonly seen = new Set<string>();
  private lastEventId: string | null = null;
  private stopped = false;
  private hasOpened = false;
  private attempt = 0;
  private connection: AbortController | null = null;
  private wake: (() => void) | null = null;

  constructor(private readonly options: RfpTicketStreamOptions) {}

  start(): void {
    void this.run();
  }

  stop(): void {
    this.stopped = true;
    this.connection?.abort();
    this.wake?.();
    this.options.onStatus({ state: "closed", attempt: this.attempt, retryInMs: null });
  }

  /** Vuelve a la red (evento `online`): reintenta ya, sin esperar al backoff. */
  retryNow(): void {
    this.wake?.();
  }

  /** Corta la conexión actual (evento `offline`) para reconectar con backoff. */
  dropConnection(): void {
    this.connection?.abort();
  }

  private async run(): Promise<void> {
    this.options.onStatus({ state: "connecting", attempt: 0, retryInMs: null });
    while (!this.stopped) {
      try {
        await this.connectOnce();
      } catch (error) {
        // 401: `apiFetch` ya redirige al login; no tiene sentido reintentar.
        if (error instanceof StreamClosedError && error.status === 401) {
          this.stop();
          return;
        }
      }
      if (this.stopped) return;
      const delay = reconnectDelayMs(this.attempt, this.options.random);
      this.attempt += 1;
      this.options.onStatus({ state: "reconnecting", attempt: this.attempt, retryInMs: delay });
      await this.sleep(delay);
    }
  }

  private async connectOnce(): Promise<void> {
    const connection = new AbortController();
    this.connection = connection;
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (this.lastEventId) headers["Last-Event-ID"] = this.lastEventId;
    const fetchStream = this.options.fetchStream ?? apiFetch;
    const response = await fetchStream(RFP_EVENTS_API, {
      headers,
      signal: connection.signal,
      cache: "no-store",
    });
    if (!response.ok || !response.body) throw new StreamClosedError(response.status);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parse = createSseParser();
    const staleAfterMs = this.options.staleAfterMs ?? RFP_STREAM_STALE_MS;
    let watchdog = setTimeout(() => connection.abort(), staleAfterMs);
    let opened = false;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) return;
        clearTimeout(watchdog);
        watchdog = setTimeout(() => connection.abort(), staleAfterMs);
        // Abierta de verdad cuando llega el primer frame (`: conectado`), no con las cabeceras.
        if (!opened) {
          opened = true;
          this.markOpen();
        }
        for (const message of parse(decoder.decode(value, { stream: true }))) {
          this.handle(message);
        }
      }
    } finally {
      clearTimeout(watchdog);
      reader.cancel().catch(() => undefined);
    }
  }

  private markOpen(): void {
    const reconnected = this.hasOpened;
    this.hasOpened = true;
    this.attempt = 0;
    this.options.onStatus({ state: "open", attempt: 0, retryInMs: null });
    if (reconnected) this.options.onReconnected?.();
  }

  private handle(message: SseMessage): void {
    if (message.id) this.lastEventId = message.id;
    if (message.event !== RFP_TICKET_CREATED) return;
    let payload: unknown;
    try {
      payload = JSON.parse(message.data);
    } catch {
      return;
    }
    if (!isTicketCreatedEvent(payload) || this.seen.has(payload.ticket_id)) return;
    this.seen.add(payload.ticket_id);
    this.options.onTicket(payload);
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      const finish = () => {
        clearTimeout(timer);
        this.wake = null;
        resolve();
      };
      const timer = setTimeout(finish, ms);
      this.wake = finish;
    });
  }
}
