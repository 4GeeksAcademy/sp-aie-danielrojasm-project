/**
 * TelemetryService del backoffice: captura, cola y envío por lotes.
 *
 * Todo el tracking pasa por `track()`. El servicio completa el Event Envelope
 * (`eventId`, `timestamp`, `sessionId`, `userId`, `schemaVersion`,
 * `requestId`, `source`, `environment`) en el momento de la captura, guarda el
 * evento en una cola en memoria y la envía a `NEXT_PUBLIC_TELEMETRY_ENDPOINT`:
 *
 * - en lote, cada 10 s o al llegar a 20 eventos, lo que ocurra antes;
 * - con `navigator.sendBeacon` cuando la pestaña se oculta o se cierra;
 * - con hasta 3 reintentos (1 s, 2 s, 4 s) si la red o la ingesta fallan; después
 *   el lote se descarta: la telemetría nunca bloquea al operador.
 *
 * Es el único módulo que llama a la ingesta: ningún componente usa `fetch`
 * para telemetría. Separa uso y perfil: aquí solo viajan eventos append-only;
 * el perfil (nombre, rol, preferencias) sigue en la API.
 */
import {
  EVENT_ALLOWLISTS,
  TELEMETRY_SCHEMA_VERSION,
  type BackofficeEventProperties,
  type BackofficeEventType,
} from "@/lib/telemetry-events";

export type TelemetryEnvironment = "development" | "staging" | "production";

export interface TelemetryEvent<T extends BackofficeEventType = BackofficeEventType> {
  eventId: string;
  timestamp: string;
  sessionId: string;
  userId: string;
  event_type: T;
  schemaVersion: string;
  requestId: string;
  source: "backoffice";
  environment: TelemetryEnvironment;
  properties: BackofficeEventProperties[T];
}

/** Por qué se vacía la cola sin esperar: pestaña oculta o página que se va. */
export type PageHideReason = "hidden" | "pagehide";

export interface TelemetryTransport {
  /** Envío normal; resuelve con el estado HTTP o rechaza si no hay red. */
  send(endpoint: string, body: string): Promise<number>;
  /** Envío que sobrevive al cierre de la página; `false` si el navegador no lo encola. */
  beacon(endpoint: string, body: string): boolean;
}

interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface TelemetryServiceOptions {
  endpoint: string | null;
  environment: TelemetryEnvironment;
  transport: TelemetryTransport;
  /** Sesión por pestaña (`sessionStorage`). */
  sessionStore?: KeyValueStore | null;
  /** Momento del login, compartido entre pestañas como el token (`localStorage`). */
  loginStore?: KeyValueStore | null;
  batchSize?: number;
  flushIntervalMs?: number;
  maxRetries?: number;
  retryBaseDelayMs?: number;
  maxQueueSize?: number;
  now?: () => number;
  uuid?: () => string;
  warn?: (message: string) => void;
}

export const BATCH_SIZE = 20;
export const FLUSH_INTERVAL_MS = 10_000;
export const MAX_RETRIES = 3;
export const RETRY_BASE_DELAY_MS = 1_000;
/** Con la ingesta caída se guardan como mucho estos eventos; se descartan los más antiguos. */
export const MAX_QUEUE_SIZE = 200;

const SESSION_ID_KEY = "trackflow_session_id";
const LOGIN_AT_KEY = "trackflow_login_at";
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ENVIRONMENTS: readonly TelemetryEnvironment[] = ["development", "staging", "production"];

/** UUID v4; `crypto.randomUUID` solo existe en contextos seguros (https, localhost). */
export function createUuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function safeRead(store: KeyValueStore | null | undefined, key: string): string | null {
  try {
    return store?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function safeWrite(store: KeyValueStore | null | undefined, key: string, value: string | null): void {
  try {
    if (value === null) store?.removeItem(key);
    else store?.setItem(key, value);
  } catch {
    // Almacenamiento bloqueado (modo privado, cuota): la sesión vive solo en memoria.
  }
}

export class TelemetryService {
  private readonly options: Required<Omit<TelemetryServiceOptions, "sessionStore" | "loginStore">> &
    Pick<TelemetryServiceOptions, "sessionStore" | "loginStore">;
  private queue: TelemetryEvent[] = [];
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  /** Lotes esperando reintento: si la pestaña se cierra, salen por beacon. */
  private readonly retrying = new Map<number, { events: TelemetryEvent[]; timer: ReturnType<typeof setTimeout> }>();
  private nextRetryId = 0;
  private readonly hideListeners = new Set<(reason: PageHideReason) => void>();
  private userId = "anonymous";
  private memorySessionId: string | null = null;
  private requestId: string | null = null;
  private droppedEvents = 0;

  constructor(options: TelemetryServiceOptions) {
    this.options = {
      batchSize: BATCH_SIZE,
      flushIntervalMs: FLUSH_INTERVAL_MS,
      maxRetries: MAX_RETRIES,
      retryBaseDelayMs: RETRY_BASE_DELAY_MS,
      maxQueueSize: MAX_QUEUE_SIZE,
      now: Date.now,
      uuid: createUuid,
      warn: (message) => console.warn(message),
      ...options,
    };
  }

  get pendingEvents(): number {
    return this.queue.length;
  }

  get droppedCount(): number {
    return this.droppedEvents;
  }

  // -------------------------------------------------------------------------
  // Captura
  // -------------------------------------------------------------------------

  track<T extends BackofficeEventType>(eventType: T, properties: BackofficeEventProperties[T]): void {
    if (!this.options.endpoint) return;
    const event: TelemetryEvent<T> = {
      eventId: this.options.uuid(),
      // Momento de la captura, no del envío.
      timestamp: new Date(this.options.now()).toISOString(),
      sessionId: this.sessionId(),
      userId: this.userId,
      event_type: eventType,
      schemaVersion: TELEMETRY_SCHEMA_VERSION,
      requestId: this.requestId ?? this.options.uuid(),
      source: "backoffice",
      environment: this.options.environment,
      properties: this.allowed(eventType, properties),
    };
    this.queue.push(event as TelemetryEvent);
    if (this.queue.length > this.options.maxQueueSize) {
      const overflow = this.queue.length - this.options.maxQueueSize;
      this.queue.splice(0, overflow);
      this.droppedEvents += overflow;
    }
    if (this.queue.length >= this.options.batchSize) this.flush();
    else if (this.flushTimer === null) {
      this.flushTimer = setTimeout(() => this.flush(), this.options.flushIntervalMs);
    }
  }

  /** Los eventos capturados dentro de `fn` comparten el `requestId` de esa llamada a la API. */
  withRequestId<R>(requestId: string, fn: () => R): R {
    const previous = this.requestId;
    this.requestId = requestId;
    try {
      return fn();
    } finally {
      this.requestId = previous;
    }
  }

  private allowed<T extends BackofficeEventType>(
    eventType: T,
    properties: BackofficeEventProperties[T],
  ): BackofficeEventProperties[T] {
    const allowlist = EVENT_ALLOWLISTS[eventType] as readonly string[];
    const filtered: Record<string, unknown> = {};
    const dropped: string[] = [];
    for (const [key, value] of Object.entries(properties)) {
      if (allowlist.includes(key)) filtered[key] = value;
      else dropped.push(key);
    }
    if (dropped.length > 0) {
      // Solo el nombre de la clave: su valor podría ser un dato personal.
      this.options.warn(`Telemetría: ${eventType} descarta claves fuera del allowlist: ${dropped.join(", ")}`);
    }
    return filtered as BackofficeEventProperties[T];
  }

  // -------------------------------------------------------------------------
  // Sesión y usuario
  // -------------------------------------------------------------------------

  sessionId(): string {
    const stored = safeRead(this.options.sessionStore, SESSION_ID_KEY);
    if (stored && UUID_V4.test(stored)) return stored;
    const created = this.memorySessionId ?? this.options.uuid();
    this.memorySessionId = created;
    safeWrite(this.options.sessionStore, SESSION_ID_KEY, created);
    return created;
  }

  /** Login correcto: sesión nueva en esta pestaña y hora del login. */
  startSession(): void {
    this.memorySessionId = this.options.uuid();
    safeWrite(this.options.sessionStore, SESSION_ID_KEY, this.memorySessionId);
    safeWrite(this.options.loginStore, LOGIN_AT_KEY, String(this.options.now()));
  }

  /** Logout o sesión caducada: el siguiente evento abre otra sesión, anónima. */
  endSession(): void {
    this.memorySessionId = null;
    this.userId = "anonymous";
    safeWrite(this.options.sessionStore, SESSION_ID_KEY, null);
    safeWrite(this.options.loginStore, LOGIN_AT_KEY, null);
  }

  /** Segundos desde el login, o `null` si no se conoce (sesión anterior a la telemetría). */
  sessionAgeSeconds(): number | null {
    const loginAt = Number(safeRead(this.options.loginStore, LOGIN_AT_KEY));
    if (!Number.isFinite(loginAt) || loginAt <= 0) return null;
    return Math.max(0, Math.round((this.options.now() - loginAt) / 1000));
  }

  /** `userId` = id del usuario autenticado (nunca el email); `anonymous` sin sesión. */
  setUser(userId: string | null): void {
    this.userId = userId && UUID_V4.test(userId) ? userId : "anonymous";
  }

  // -------------------------------------------------------------------------
  // Envío
  // -------------------------------------------------------------------------

  /** Envía la cola en lotes de `batchSize` por `fetch`, con reintentos. */
  flush(): void {
    this.clearFlushTimer();
    const endpoint = this.options.endpoint;
    if (!endpoint) return;
    while (this.queue.length > 0) {
      void this.send(endpoint, this.queue.splice(0, this.options.batchSize), 0);
    }
  }

  private async send(endpoint: string, events: TelemetryEvent[], attempt: number): Promise<void> {
    let status = 0;
    try {
      status = await this.options.transport.send(endpoint, JSON.stringify({ events }));
    } catch {
      status = 0; // sin red o ingesta inaccesible
    }
    if (status >= 200 && status < 300) return;
    const retryable = status === 0 || status === 429 || status >= 500;
    if (!retryable) {
      // 4xx: el lote no cumple el contrato; reenviarlo no lo arreglaría.
      this.options.warn(`Telemetría: la ingesta rechazó un lote de ${events.length} eventos (${status}).`);
      return;
    }
    if (attempt >= this.options.maxRetries) {
      this.options.warn(
        `Telemetría: se descartan ${events.length} eventos tras ${attempt + 1} intentos (${status || "sin red"}).`,
      );
      return;
    }
    const id = this.nextRetryId++;
    const delay = this.options.retryBaseDelayMs * 2 ** attempt;
    const timer = setTimeout(() => {
      this.retrying.delete(id);
      void this.send(endpoint, events, attempt + 1);
    }, delay);
    this.retrying.set(id, { events, timer });
  }

  /**
   * La pestaña se oculta o se va: primero los oyentes añaden sus últimos
   * eventos (Web Vitals, formularios abandonados) y después todo lo pendiente
   * sale por `sendBeacon`, que el navegador entrega aunque la página se destruya.
   */
  flushOnHide(reason: PageHideReason): void {
    for (const listener of this.hideListeners) {
      try {
        listener(reason);
      } catch {
        // Un oyente roto no impide vaciar la cola.
      }
    }
    this.clearFlushTimer();
    const endpoint = this.options.endpoint;
    if (!endpoint) return;
    const pending = [...this.queue];
    this.queue = [];
    for (const [id, retry] of this.retrying) {
      clearTimeout(retry.timer);
      pending.push(...retry.events);
      this.retrying.delete(id);
    }
    for (let start = 0; start < pending.length; start += this.options.batchSize) {
      const events = pending.slice(start, start + this.options.batchSize);
      const body = JSON.stringify({ events });
      if (!this.options.transport.beacon(endpoint, body)) {
        // Beacon no disponible o lote demasiado grande: fetch con keepalive, sin reintentos.
        void this.options.transport.send(endpoint, body).catch(() => undefined);
      }
    }
  }

  onPageHide(listener: (reason: PageHideReason) => void): () => void {
    this.hideListeners.add(listener);
    return () => this.hideListeners.delete(listener);
  }

  private clearFlushTimer(): void {
    if (this.flushTimer !== null) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
  }
}

// ---------------------------------------------------------------------------
// Instancia del navegador
// ---------------------------------------------------------------------------

function readEnvironment(value: string | undefined): TelemetryEnvironment {
  return ENVIRONMENTS.find((environment) => environment === value) ?? "development";
}

const browserTransport: TelemetryTransport = {
  async send(endpoint, body) {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      // Permite que el envío termine aunque el usuario cambie de página.
      keepalive: true,
    });
    return response.status;
  },
  beacon(endpoint, body) {
    if (typeof navigator === "undefined" || typeof navigator.sendBeacon !== "function") return false;
    // text/plain es un tipo "simple": no necesita preflight CORS si la ingesta es de otro origen.
    return navigator.sendBeacon(endpoint, new Blob([body], { type: "text/plain;charset=UTF-8" }));
  },
};

let browserService: TelemetryService | null = null;

function service(): TelemetryService | null {
  // Solo en un navegador real: en el servidor (SSR) y en entornos sin DOM no hay telemetría.
  if (typeof window === "undefined" || typeof document === "undefined") return null;
  if (browserService) return browserService;
  // Next inserta las NEXT_PUBLIC_* en el bundle al compilar: solo funcionan
  // con acceso literal a `process.env.NEXT_PUBLIC_...`.
  const endpoint = process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT?.trim() || null;
  if (!endpoint) {
    console.warn("Telemetría desactivada: falta NEXT_PUBLIC_TELEMETRY_ENDPOINT.");
  }
  browserService = new TelemetryService({
    endpoint,
    environment: readEnvironment(process.env.NEXT_PUBLIC_TELEMETRY_ENVIRONMENT),
    transport: browserTransport,
    sessionStore: window.sessionStorage,
    loginStore: window.localStorage,
  });
  const instance = browserService;
  // En `window` y en fase de burbuja: `visibilitychange` sale de `document`, así
  // que este oyente va después de los de web-vitals, que publican CLS e INP al
  // ocultarse la pestaña. Así esas métricas entran en el último lote.
  window.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") instance.flushOnHide("hidden");
  });
  window.addEventListener("pagehide", () => instance.flushOnHide("pagehide"));
  return browserService;
}

/**
 * Única puerta de entrada del tracking del backoffice. El componente solo
 * aporta el tipo de evento y sus propiedades de negocio; el envelope lo
 * completa el servicio.
 */
export function track<T extends BackofficeEventType>(
  eventType: T,
  properties: BackofficeEventProperties[T],
): void {
  service()?.track(eventType, properties);
}

export function withTelemetryRequestId<R>(requestId: string, fn: () => R): R {
  const instance = service();
  return instance ? instance.withRequestId(requestId, fn) : fn();
}

export function setTelemetryUser(userId: string | null): void {
  service()?.setUser(userId);
}

export function startTelemetrySession(): void {
  service()?.startSession();
}

export function endTelemetrySession(): void {
  service()?.endSession();
}

export function telemetrySessionId(): string | null {
  return service()?.sessionId() ?? null;
}

export function telemetrySessionAgeSeconds(): number | null {
  return service()?.sessionAgeSeconds() ?? null;
}

export function onTelemetryPageHide(listener: (reason: PageHideReason) => void): () => void {
  return service()?.onPageHide(listener) ?? (() => undefined);
}
