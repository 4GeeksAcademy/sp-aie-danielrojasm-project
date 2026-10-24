/**
 * Notificación de RFPs nuevas por SSE (`lib/rfp-events.ts`): parser del
 * stream, backoff, deduplicación y reconexión con `Last-Event-ID`. La red se
 * simula con `Response` + `ReadableStream`; no se llama a la API.
 */
import {
  RFP_RECONNECT_MAX_MS,
  RfpTicketStream,
  createSseParser,
  mergeLiveTickets,
  reconnectDelayMs,
  type RfpStreamStatus,
  type RfpTicketCreatedEvent,
} from "@/lib/rfp-events";
import type { RfpTicketListItem } from "@/lib/rfps";

function ticketEvent(ticketId: string, createdAt = "2026-07-24T14:32:00Z"): RfpTicketCreatedEvent {
  return {
    ticket_id: ticketId,
    rfp_id: `rfp-${ticketId}`,
    client_name: "Northline Apparel",
    client_country: "US",
    services_requested: ["warehousing", "last_mile"],
    status: "analizando",
    original_filename: `${ticketId}.pdf`,
    created_at: createdAt,
  };
}

function frame(id: string, event: RfpTicketCreatedEvent): string {
  return `event: rfp_ticket_created\ndata: ${JSON.stringify(event)}\nid: ${id}\n\n`;
}

/** Respuesta SSE que envía `chunks` y, si `keepOpen`, sigue abierta hasta que se aborta. */
function sseResponse(chunks: string[], signal: AbortSignal, keepOpen = false): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      if (!keepOpen) controller.close();
      signal.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

async function waitFor(condition: () => boolean): Promise<void> {
  const deadline = Date.now() + 2000;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error("La condición no se cumplió a tiempo.");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

describe("createSseParser", () => {
  it("devuelve solo mensajes completos aunque lleguen partidos entre trozos", () => {
    const parse = createSseParser();
    const event = ticketEvent("tkt_1");
    const wire = `: conectado\n\n${frame("1-0", event)}`;

    expect(parse(wire.slice(0, 30))).toEqual([]);
    expect(parse(wire.slice(30))).toEqual([
      { id: "1-0", event: "rfp_ticket_created", data: JSON.stringify(event) },
    ]);
  });

  it("ignora comentarios de keep-alive y acepta CRLF y data en varias líneas", () => {
    const parse = createSseParser();

    expect(parse(": ping\r\n\r\n")).toEqual([]);
    expect(parse("data: a\r\ndata: b\r\n\r\n")).toEqual([{ id: null, event: "message", data: "a\nb" }]);
  });
});

describe("reconnectDelayMs", () => {
  it("crece de forma exponencial con jitter y no pasa del tope", () => {
    expect([0, 1, 2, 3].map((attempt) => reconnectDelayMs(attempt, () => 0))).toEqual([500, 1000, 2000, 4000]);
    expect([0, 1, 2, 3].map((attempt) => reconnectDelayMs(attempt, () => 1))).toEqual([1000, 2000, 4000, 8000]);
    expect(reconnectDelayMs(20, () => 1)).toBe(RFP_RECONNECT_MAX_MS);
  });
});

describe("mergeLiveTickets", () => {
  const fromApi: RfpTicketListItem = {
    ticket_id: "tkt_1",
    status: "analisis_completo",
    original_filename: "tkt_1.pdf",
    client_name: "Northline Apparel",
    client_country: "US",
    departments_needed: ["warehouse"],
    attempts: 1,
    last_error: null,
    response_handoff_ready: false,
    created_at: "2026-07-24T14:00:00Z",
    updated_at: "2026-07-24T14:05:00Z",
  };

  it("añade las RFPs notificadas sin duplicar las que ya trae la API", () => {
    const rows = mergeLiveTickets([fromApi], [ticketEvent("tkt_2"), ticketEvent("tkt_1")]);

    expect(rows.map((row) => row.ticket_id)).toEqual(["tkt_2", "tkt_1"]);
    // Para un ticket que ya está en la lista manda la API, que tiene el estado más reciente.
    expect(rows[1]).toBe(fromApi);
    expect(rows[0]).toMatchObject({ status: "analizando", original_filename: "tkt_2.pdf", departments_needed: [] });
  });
});

describe("RfpTicketStream", () => {
  it("reconecta con backoff, recupera con Last-Event-ID y no repite tickets", async () => {
    const requests: Headers[] = [];
    const tickets: string[] = [];
    const statuses: RfpStreamStatus[] = [];
    let reconnections = 0;
    const responses = [
      // 1: llega tkt_1 y la conexión se corta.
      (signal: AbortSignal) => sseResponse([": conectado\n\n", frame("1-0", ticketEvent("tkt_1"))], signal),
      // 2: sin red.
      () => Promise.reject(new TypeError("Failed to fetch")),
      // 3: la API reenvía lo posterior a 1-0; tkt_1 repetido no debe notificarse otra vez.
      (signal: AbortSignal) =>
        sseResponse(
          [": conectado\n\n", frame("1-0", ticketEvent("tkt_1")), frame("2-0", ticketEvent("tkt_2"))],
          signal,
          true,
        ),
    ];

    const stream: RfpTicketStream = new RfpTicketStream({
      fetchStream: async (_url, init) => {
        requests.push(new Headers(init.headers));
        const next = responses.shift();
        if (!next) throw new Error("Sin más respuestas simuladas.");
        return next(init.signal as AbortSignal);
      },
      onTicket: (event) => tickets.push(event.ticket_id),
      onStatus: (status) => {
        statuses.push(status);
        // Sin esperar al temporizador real: equivale al evento `online` del navegador.
        if (status.state === "reconnecting") queueMicrotask(() => stream.retryNow());
      },
      onReconnected: () => {
        reconnections += 1;
      },
      random: () => 0,
    });

    stream.start();
    await waitFor(() => tickets.length === 2);
    stream.stop();

    expect(tickets).toEqual(["tkt_1", "tkt_2"]);
    expect(requests.map((headers) => headers.get("Last-Event-ID"))).toEqual([null, "1-0", "1-0"]);
    expect(requests.every((headers) => headers.get("Accept") === "text/event-stream")).toBe(true);
    expect(
      statuses.filter((status) => status.state === "reconnecting").map(({ attempt, retryInMs }) => [attempt, retryInMs]),
    ).toEqual([
      [1, 500],
      [2, 1000],
    ]);
    expect(statuses.map((status) => status.state)).toEqual([
      "connecting",
      "open",
      "reconnecting",
      "reconnecting",
      "open",
      "closed",
    ]);
    expect(reconnections).toBe(1);
  });

  it("corta y reconecta una conexión que deja de recibir datos (ni siquiera el ping)", async () => {
    let calls = 0;
    const stream = new RfpTicketStream({
      fetchStream: async (_url, init) => {
        calls += 1;
        return sseResponse([": conectado\n\n"], init.signal as AbortSignal, true);
      },
      onTicket: () => undefined,
      onStatus: (status) => {
        if (status.state === "reconnecting") queueMicrotask(() => stream.retryNow());
      },
      staleAfterMs: 30,
    });

    stream.start();
    await waitFor(() => calls >= 2);
    stream.stop();
  });

  it("se detiene sin reintentar si la sesión caducó (401)", async () => {
    let calls = 0;
    const statuses: string[] = [];
    const stream = new RfpTicketStream({
      fetchStream: async () => {
        calls += 1;
        return new Response(null, { status: 401 });
      },
      onTicket: () => undefined,
      onStatus: (status) => statuses.push(status.state),
    });

    stream.start();
    await waitFor(() => statuses.includes("closed"));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(calls).toBe(1);
    expect(statuses).toEqual(["connecting", "closed"]);
  });
});
