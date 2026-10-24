/**
 * Chat con el First-line CX agent: cliente de `/agent/chat/*` (REST para la
 * sesión y WebSocket para la conversación).
 *
 * - El socket va por el rewrite `/api/agent/*` (mismo origen) y se autentica con
 *   el JWT del backoffice en `?token=`: el navegador no puede poner
 *   `Authorization` en el handshake.
 * - Cada frame es `{ event, data }` (contrato del BRIEFING de la Parte 2). La
 *   respuesta llega en `token_chunk` y se va pintando; `generation_completed`
 *   trae el texto final (tras el guard de salida) y es el que queda.
 * - Reconexión con el mismo backoff que el SSE de RFPs. Al reconectar, el
 *   servidor manda primero `session_snapshot` con el hilo completo; hasta
 *   entonces no se aceptan tokens (`ready: false`).
 */
import { clearAccessToken, getAccessToken, requestJson } from "@/lib/api-client";
import { reconnectDelayMs, type RfpStreamState } from "@/lib/rfp-events";

const CHAT_API = "/api/agent/chat/sessions";

/** Mismo límite que la API (`MAX_QUESTION_LENGTH`). */
export const CHAT_MESSAGE_MAX_LENGTH = 1000;

/** Cierres del servidor que no se reintentan. */
export const CLOSE_UNAUTHENTICATED = 1008;
export const CLOSE_SESSION_NOT_FOUND = 4404;
export const CLOSE_FORBIDDEN = 4403;

export type ChatSessionStatus = "active" | "interrupted" | "closed";
export type ChatMessageRole = "user" | "assistant";
export type ChatMessageStatus = "streaming" | "completed" | "interrupted" | "failed";

export interface ChatSession {
  session_id: string;
  agent_id: "first_line_cx";
  user_id: string;
  client_id: string | null;
  status: ChatSessionStatus;
  created_at: string;
}

export interface ChatMessage {
  message_id: string;
  session_id: string;
  role: ChatMessageRole;
  text: string;
  status: ChatMessageStatus;
  created_at: string;
}

export interface SessionSnapshotData {
  session_id: string;
  status: ChatSessionStatus;
  messages: ChatMessage[];
  /** Generación en curso y último `sequence` incluido en su texto. */
  generation: { message_id: string; sequence: number } | null;
}

export type ChatServerEvent =
  | { event: "session_snapshot"; data: SessionSnapshotData }
  | { event: "user_message"; data: { session_id: string; message_id: string; text: string } }
  | {
      event: "token_chunk";
      data: { session_id: string; message_id: string; token: string; sequence: number };
    }
  | {
      event: "generation_interrupted";
      data: {
        session_id: string;
        message_id: string;
        status: "interrupted";
        text: string;
        new_input: string;
      };
    }
  | { event: "generation_completed"; data: { session_id: string; message_id: string; text: string } }
  | { event: "generation_failed"; data: { session_id: string; message_id: string; detail: string } }
  | { event: "chat_error"; data: { session_id: string; detail: string } };

export type ChatClientFrame =
  | { event: "user_message"; data: { session_id: string; text: string } }
  | { event: "interrupt_requested"; data: { session_id: string; new_input: string } };

const SERVER_EVENTS = new Set<ChatServerEvent["event"]>([
  "session_snapshot",
  "user_message",
  "token_chunk",
  "generation_interrupted",
  "generation_completed",
  "generation_failed",
  "chat_error",
]);

export const chatMessageStatusLabels: Record<ChatMessageStatus, string> = {
  streaming: "Escribiendo…",
  completed: "Respondido",
  interrupted: "Interrumpido",
  failed: "Sin respuesta",
};

export const chatConnectionLabels: Record<RfpStreamState, string> = {
  connecting: "Conectando…",
  open: "En vivo",
  reconnecting: "Sin conexión · reintentando",
  closed: "Chat desconectado",
};

export async function createChatSession(): Promise<ChatSession> {
  return requestJson<ChatSession>(
    CHAT_API,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
    "No se pudo abrir la conversación con el agente.",
  );
}

export async function getChatSession(sessionId: string): Promise<ChatSession> {
  return requestJson<ChatSession>(
    `${CHAT_API}/${encodeURIComponent(sessionId)}`,
    {},
    "No se pudo recuperar la conversación con el agente.",
  );
}

export function chatSocketUrl(
  sessionId: string,
  token: string,
  location: Pick<Location, "protocol" | "host">,
): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}${CHAT_API}/${encodeURIComponent(sessionId)}/ws?token=${encodeURIComponent(token)}`;
}

/** Frame del servidor ya validado, o `null` si no es un evento conocido. */
export function parseServerEvent(raw: string): ChatServerEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const { event, data } = value as { event?: unknown; data?: unknown };
  if (typeof event !== "string" || typeof data !== "object" || data === null) return null;
  if (!SERVER_EVENTS.has(event as ChatServerEvent["event"])) return null;
  return value as ChatServerEvent;
}

export interface ChatThread {
  messages: ChatMessage[];
  /** Mensaje del asistente en curso y último `sequence` aplicado. */
  streaming: { messageId: string; sequence: number } | null;
  /** El usuario escribió y aún no llegó el primer token. */
  awaitingReply: boolean;
  /** Hay snapshot de esta conexión: hasta entonces no se aceptan tokens. */
  ready: boolean;
  error: string | null;
}

export const emptyThread: ChatThread = {
  messages: [],
  streaming: null,
  awaitingReply: false,
  ready: false,
  error: null,
};

export type ChatThreadAction =
  | ChatServerEvent
  | { event: "disconnected" }
  | { event: "dismiss_error" }
  | { event: "reset" };

function upsert(messages: ChatMessage[], message: ChatMessage): ChatMessage[] {
  return messages.some((item) => item.message_id === message.message_id)
    ? messages.map((item) => (item.message_id === message.message_id ? message : item))
    : [...messages, message];
}

function patch(
  messages: ChatMessage[],
  base: Omit<ChatMessage, "text" | "status">,
  changes: Pick<ChatMessage, "text" | "status">,
): ChatMessage[] {
  const current = messages.find((item) => item.message_id === base.message_id);
  return upsert(messages, { ...(current ?? base), ...changes });
}

function assistantBase(sessionId: string, messageId: string): Omit<ChatMessage, "text" | "status"> {
  return { message_id: messageId, session_id: sessionId, role: "assistant", created_at: new Date().toISOString() };
}

/** Aplica un evento al hilo (función pura: la usa `useReducer`). */
export function chatThreadReducer(state: ChatThread, action: ChatThreadAction): ChatThread {
  switch (action.event) {
    case "disconnected":
      return { ...state, ready: false };
    case "dismiss_error":
      return { ...state, error: null };
    case "reset":
      return emptyThread;
    case "session_snapshot": {
      const { messages, generation } = action.data;
      return {
        messages,
        streaming: generation ? { messageId: generation.message_id, sequence: generation.sequence } : null,
        awaitingReply: false,
        ready: true,
        error: null,
      };
    }
    case "user_message": {
      if (!state.ready) return state;
      const { session_id, message_id, text } = action.data;
      const message: ChatMessage = {
        message_id,
        session_id,
        role: "user",
        text,
        status: "completed",
        created_at: new Date().toISOString(),
      };
      return { ...state, messages: upsert(state.messages, message), awaitingReply: true, error: null };
    }
    case "token_chunk": {
      if (!state.ready) return state;
      const { session_id, message_id, token, sequence } = action.data;
      const same = state.streaming?.messageId === message_id;
      // Ya incluido en el snapshot (o repetido): no se pinta dos veces.
      if (same && state.streaming && sequence <= state.streaming.sequence) return state;
      const current = state.messages.find((item) => item.message_id === message_id);
      return {
        ...state,
        messages: patch(state.messages, assistantBase(session_id, message_id), {
          text: (current?.text ?? "") + token,
          status: "streaming",
        }),
        streaming: { messageId: message_id, sequence },
        awaitingReply: false,
      };
    }
    case "generation_interrupted":
    case "generation_completed": {
      const { session_id, message_id, text } = action.data;
      const status = action.event === "generation_completed" ? "completed" : "interrupted";
      return {
        ...state,
        messages: patch(state.messages, assistantBase(session_id, message_id), { text, status }),
        streaming: state.streaming?.messageId === message_id ? null : state.streaming,
        awaitingReply: false,
      };
    }
    case "generation_failed": {
      const { session_id, message_id, detail } = action.data;
      const current = state.messages.find((item) => item.message_id === message_id);
      return {
        ...state,
        messages: patch(state.messages, assistantBase(session_id, message_id), {
          text: current?.text ?? "",
          status: "failed",
        }),
        streaming: state.streaming?.messageId === message_id ? null : state.streaming,
        awaitingReply: false,
        error: detail,
      };
    }
    case "chat_error":
      return { ...state, error: action.data.detail };
  }
}

export interface ChatConnectionStatus {
  state: RfpStreamState;
  attempt: number;
  retryInMs: number | null;
}

/** Lo mínimo de `WebSocket` que usa el cliente (inyectable en los tests). */
export interface ChatSocketLike {
  readonly readyState: number;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

const SOCKET_OPEN = 1;

export interface ChatConnectionOptions {
  sessionId: string;
  onEvent: (event: ChatServerEvent) => void;
  onStatus: (status: ChatConnectionStatus) => void;
  /** La conexión se cayó: el hilo deja de aceptar tokens hasta el próximo snapshot. */
  onDisconnected: () => void;
  /** 4404: la sesión ya no existe (p. ej. Redis se vació); hay que abrir otra. */
  onSessionMissing: () => void;
  /** 4403 u otro cierre definitivo. */
  onFatal: (message: string) => void;
  /** Inyectables para los tests. */
  createSocket?: (url: string) => ChatSocketLike;
  getToken?: () => string | null;
  location?: Pick<Location, "protocol" | "host">;
  onUnauthenticated?: () => void;
  random?: () => number;
}

function redirectToLogin(): void {
  clearAccessToken();
  if (window.location.pathname !== "/login") window.location.assign("/login");
}

/**
 * Socket de una sesión con reconexión. `start()` conecta, `stop()` cierra para
 * siempre (al desmontar) y `send()` devuelve `false` si no hay conexión abierta.
 */
export class ChatConnection {
  private socket: ChatSocketLike | null = null;
  private stopped = false;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly options: ChatConnectionOptions) {}

  start(): void {
    this.options.onStatus({ state: "connecting", attempt: 0, retryInMs: null });
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.socket?.close(1000, "Vista cerrada");
    this.socket = null;
    this.options.onStatus({ state: "closed", attempt: this.attempt, retryInMs: null });
  }

  /** Vuelve la red (evento `online`): reintenta ya, sin esperar al backoff. */
  retryNow(): void {
    if (this.stopped || this.socket) return;
    if (this.timer) clearTimeout(this.timer);
    this.connect();
  }

  send(frame: ChatClientFrame): boolean {
    if (!this.socket || this.socket.readyState !== SOCKET_OPEN) return false;
    this.socket.send(JSON.stringify(frame));
    return true;
  }

  private connect(): void {
    this.timer = null;
    const token = (this.options.getToken ?? getAccessToken)();
    if (!token) {
      this.unauthenticated();
      return;
    }
    const url = chatSocketUrl(this.options.sessionId, token, this.options.location ?? window.location);
    const socket = (this.options.createSocket ?? ((target) => new WebSocket(target)))(url);
    this.socket = socket;
    socket.onopen = () => {
      this.attempt = 0;
      this.options.onStatus({ state: "open", attempt: 0, retryInMs: null });
    };
    socket.onmessage = ({ data }) => {
      if (typeof data !== "string") return;
      const event = parseServerEvent(data);
      if (event) this.options.onEvent(event);
    };
    socket.onclose = ({ code }) => this.closed(socket, code);
    // `onerror` siempre va seguido de `onclose`: la reconexión se decide allí.
    socket.onerror = () => undefined;
  }

  private closed(socket: ChatSocketLike, code: number): void {
    if (this.socket !== socket) return;
    this.socket = null;
    if (this.stopped) return;
    this.options.onDisconnected();
    if (code === CLOSE_UNAUTHENTICATED) {
      this.unauthenticated();
      return;
    }
    if (code === CLOSE_SESSION_NOT_FOUND) {
      this.stopped = true;
      this.options.onSessionMissing();
      return;
    }
    if (code === CLOSE_FORBIDDEN) {
      this.stopped = true;
      this.options.onStatus({ state: "closed", attempt: this.attempt, retryInMs: null });
      this.options.onFatal("No tienes acceso a esta conversación.");
      return;
    }
    const delay = reconnectDelayMs(this.attempt, this.options.random);
    this.attempt += 1;
    this.options.onStatus({ state: "reconnecting", attempt: this.attempt, retryInMs: delay });
    this.timer = setTimeout(() => this.connect(), delay);
  }

  private unauthenticated(): void {
    this.stopped = true;
    this.options.onStatus({ state: "closed", attempt: this.attempt, retryInMs: null });
    (this.options.onUnauthenticated ?? redirectToLogin)();
  }
}
