/**
 * Chat con el agente de CX por WebSocket (`lib/agent-chat.ts`): contrato de
 * eventos, reducer del hilo (tokens en vivo, interrupción, rehidratación) y
 * reconexión con backoff. El socket es un doble; no se llama a la API.
 */
import {
  CLOSE_SESSION_NOT_FOUND,
  CLOSE_UNAUTHENTICATED,
  ChatConnection,
  chatSocketUrl,
  chatThreadReducer,
  emptyThread,
  parseServerEvent,
  type ChatConnectionStatus,
  type ChatServerEvent,
  type ChatSocketLike,
  type ChatThread,
} from "@/lib/agent-chat";

const SESSION = "chat_0219";

function snapshot(overrides: Partial<Extract<ChatServerEvent, { event: "session_snapshot" }>["data"]> = {}) {
  return {
    event: "session_snapshot",
    data: { session_id: SESSION, status: "active", messages: [], generation: null, ...overrides },
  } as const satisfies ChatServerEvent;
}

function token(messageId: string, text: string, sequence: number): ChatServerEvent {
  return { event: "token_chunk", data: { session_id: SESSION, message_id: messageId, token: text, sequence } };
}

function apply(...events: (ChatServerEvent | { event: "disconnected" })[]): ChatThread {
  return events.reduce(chatThreadReducer, emptyThread);
}

describe("parseServerEvent", () => {
  it("acepta los eventos del contrato y descarta el resto", () => {
    expect(parseServerEvent(JSON.stringify(token("msg_1", "Tu", 7)))).toEqual(token("msg_1", "Tu", 7));
    expect(parseServerEvent("no es json")).toBeNull();
    expect(parseServerEvent(JSON.stringify({ event: "rfp_ticket_created", data: {} }))).toBeNull();
    expect(parseServerEvent(JSON.stringify({ event: "token_chunk" }))).toBeNull();
  });
});

describe("chatSocketUrl", () => {
  it("usa el mismo origen, wss en https y el token en la query", () => {
    expect(chatSocketUrl(SESSION, "a b", { protocol: "https:", host: "backoffice.example" })).toBe(
      "wss://backoffice.example/api/agent/chat/sessions/chat_0219/ws?token=a%20b",
    );
    expect(chatSocketUrl(SESSION, "t", { protocol: "http:", host: "localhost:3002" })).toMatch(/^ws:\/\/localhost:3002\//);
  });
});

describe("chatThreadReducer", () => {
  it("pinta la respuesta token a token y la cierra con el texto final", () => {
    const thread = apply(
      snapshot(),
      { event: "user_message", data: { session_id: SESSION, message_id: "msg_u", text: "¿Dónde está mi pedido?" } },
      token("msg_a", "Tu ", 1),
      token("msg_a", "pedido", 2),
    );

    expect(thread.messages.map((message) => [message.role, message.text, message.status])).toEqual([
      ["user", "¿Dónde está mi pedido?", "completed"],
      ["assistant", "Tu pedido", "streaming"],
    ]);
    expect(thread.streaming).toEqual({ messageId: "msg_a", sequence: 2 });

    const done = chatThreadReducer(thread, {
      event: "generation_completed",
      data: { session_id: SESSION, message_id: "msg_a", text: "Tu pedido está en reparto.\nFuente: Tracking" },
    });
    expect(done.messages[1]).toMatchObject({ text: "Tu pedido está en reparto.\nFuente: Tracking", status: "completed" });
    expect(done.streaming).toBeNull();
  });

  it("deja el mensaje parcial como interrumpido y la respuesta redirigida en un mensaje nuevo", () => {
    const thread = apply(
      snapshot(),
      { event: "user_message", data: { session_id: SESSION, message_id: "msg_u1", text: "rastrear" } },
      token("msg_a1", "Para rastrear", 1),
      {
        event: "generation_interrupted",
        data: {
          session_id: SESSION,
          message_id: "msg_a1",
          status: "interrupted",
          text: "Para rastrear",
          new_input: "quiero una devolución",
        },
      },
      { event: "user_message", data: { session_id: SESSION, message_id: "msg_u2", text: "quiero una devolución" } },
      token("msg_a2", "Claro", 1),
    );

    expect(thread.messages.map((message) => [message.message_id, message.status, message.text])).toEqual([
      ["msg_u1", "completed", "rastrear"],
      ["msg_a1", "interrupted", "Para rastrear"],
      ["msg_u2", "completed", "quiero una devolución"],
      ["msg_a2", "streaming", "Claro"],
    ]);
  });

  it("al reconectar no acepta tokens hasta el snapshot y no repite lo que ya trae", () => {
    const disconnected = apply(snapshot(), token("msg_a", "Hola", 1), { event: "disconnected" });
    expect(chatThreadReducer(disconnected, token("msg_a", " perdido", 2))).toBe(disconnected);

    const restored = chatThreadReducer(
      disconnected,
      snapshot({
        messages: [
          {
            message_id: "msg_a",
            session_id: SESSION,
            role: "assistant",
            text: "Hola, tu",
            status: "streaming",
            created_at: "2026-10-24T10:00:00Z",
          },
        ],
        generation: { message_id: "msg_a", sequence: 2 },
      }),
    );
    const next = [token("msg_a", " tu", 2), token("msg_a", " devolución", 3)].reduce(chatThreadReducer, restored);

    expect(next.messages[0].text).toBe("Hola, tu devolución");
    expect(next.ready).toBe(true);
  });

  it("muestra los errores del agente y del protocolo", () => {
    const failed = apply(snapshot(), token("msg_a", "Hol", 1), {
      event: "generation_failed",
      data: { session_id: SESSION, message_id: "msg_a", detail: "El agente no pudo responder." },
    });

    expect(failed.messages[0]).toMatchObject({ status: "failed", text: "Hol" });
    expect(failed.error).toBe("El agente no pudo responder.");
  });
});

class FakeSocket implements ChatSocketLike {
  readyState = 0;
  sent: string[] = [];
  onopen: ChatSocketLike["onopen"] = null;
  onmessage: ChatSocketLike["onmessage"] = null;
  onclose: ChatSocketLike["onclose"] = null;
  onerror: ChatSocketLike["onerror"] = null;

  constructor(readonly url: string) {}

  open() {
    this.readyState = 1;
    this.onopen?.({} as Event);
  }

  receive(event: ChatServerEvent) {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.drop(1000);
  }

  drop(code: number) {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }
}

function connection(overrides: Partial<ConstructorParameters<typeof ChatConnection>[0]> = {}) {
  const sockets: FakeSocket[] = [];
  const statuses: ChatConnectionStatus[] = [];
  const events: ChatServerEvent[] = [];
  const calls = { disconnected: 0, missing: 0, unauthenticated: 0 };
  const chat = new ChatConnection({
    sessionId: SESSION,
    onEvent: (event) => events.push(event),
    onStatus: (status) => statuses.push(status),
    onDisconnected: () => (calls.disconnected += 1),
    onSessionMissing: () => (calls.missing += 1),
    onFatal: () => undefined,
    onUnauthenticated: () => (calls.unauthenticated += 1),
    createSocket: (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    getToken: () => "jwt",
    location: { protocol: "http:", host: "localhost:3002" },
    random: () => 0,
    ...overrides,
  });
  return { chat, sockets, statuses, events, calls };
}

describe("ChatConnection", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("reconecta con backoff progresivo a la misma sesión y vuelve a pedir el snapshot", () => {
    const { chat, sockets, statuses, events, calls } = connection();
    chat.start();
    sockets[0].open();
    sockets[0].receive(snapshot());

    sockets[0].drop(1006);
    expect(calls.disconnected).toBe(1);
    expect(statuses.at(-1)).toEqual({ state: "reconnecting", attempt: 1, retryInMs: 500 });
    jest.advanceTimersByTime(500);
    sockets[1].drop(1006);
    expect(statuses.at(-1)).toEqual({ state: "reconnecting", attempt: 2, retryInMs: 1000 });
    jest.advanceTimersByTime(1000);
    sockets[2].open();

    expect(sockets.map((socket) => socket.url)).toEqual(Array(3).fill(sockets[0].url));
    expect(sockets[0].url).toContain(`/sessions/${SESSION}/ws?token=jwt`);
    expect(statuses.at(-1)).toEqual({ state: "open", attempt: 0, retryInMs: null });
    expect(events).toEqual([snapshot()]);
    chat.stop();
  });

  it("solo envía con la conexión abierta", () => {
    const { chat, sockets } = connection();
    chat.start();
    const frame = { event: "user_message", data: { session_id: SESSION, text: "hola" } } as const;

    expect(chat.send(frame)).toBe(false);
    sockets[0].open();
    expect(chat.send(frame)).toBe(true);
    expect(JSON.parse(sockets[0].sent[0])).toEqual(frame);
    chat.stop();
  });

  it("no reintenta si el token no es válido o la sesión ya no existe", () => {
    const unauthenticated = connection();
    unauthenticated.chat.start();
    unauthenticated.sockets[0].drop(CLOSE_UNAUTHENTICATED);
    jest.advanceTimersByTime(60_000);
    expect(unauthenticated.calls.unauthenticated).toBe(1);
    expect(unauthenticated.sockets).toHaveLength(1);

    const missing = connection();
    missing.chat.start();
    missing.sockets[0].drop(CLOSE_SESSION_NOT_FOUND);
    jest.advanceTimersByTime(60_000);
    expect(missing.calls.missing).toBe(1);
    expect(missing.sockets).toHaveLength(1);
  });

  it("sin token no abre el socket", () => {
    const { chat, sockets, calls } = connection({ getToken: () => null });
    chat.start();

    expect(sockets).toHaveLength(0);
    expect(calls.unauthenticated).toBe(1);
  });
});
