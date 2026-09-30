import fs from "node:fs";
import path from "node:path";
import {
  BATCH_SIZE,
  FLUSH_INTERVAL_MS,
  MAX_QUEUE_SIZE,
  TelemetryService,
  type TelemetryEvent,
  type TelemetryTransport,
} from "@/lib/telemetry";
import { EVENT_ALLOWLISTS, type BackofficeEventType } from "@/lib/telemetry-events";

const ENDPOINT = "http://localhost:8000/telemetry/events";
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const USER_ID = "4b3f1c2d-9e8a-4d7c-b6a5-1f2e3d4c5b6a";

class MemoryStore {
  private readonly values = new Map<string, string>();
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
  removeItem(key: string) {
    this.values.delete(key);
  }
}

interface FakeTransport extends TelemetryTransport {
  sent: TelemetryEvent[][];
  beacons: TelemetryEvent[][];
  statuses: (number | Error)[];
}

function fakeTransport(statuses: (number | Error)[] = []): FakeTransport {
  const transport: FakeTransport = {
    sent: [],
    beacons: [],
    statuses,
    async send(_endpoint, body) {
      transport.sent.push((JSON.parse(body) as { events: TelemetryEvent[] }).events);
      const next = transport.statuses.shift() ?? 200;
      if (next instanceof Error) throw next;
      return next;
    },
    beacon(_endpoint, body) {
      transport.beacons.push((JSON.parse(body) as { events: TelemetryEvent[] }).events);
      return true;
    },
  };
  return transport;
}

function createService(transport = fakeTransport(), overrides = {}) {
  const warnings: string[] = [];
  const service = new TelemetryService({
    endpoint: ENDPOINT,
    environment: "development",
    transport,
    sessionStore: new MemoryStore(),
    loginStore: new MemoryStore(),
    warn: (message) => warnings.push(message),
    ...overrides,
  });
  return { service, transport, warnings };
}

function sidebarClick(service: TelemetryService, key = "inventory_stock") {
  service.track("sidebar_item_clicked", { item_key: key, is_upcoming: false, device_class: "desktop" });
}

/** Deja correr las promesas pendientes (envíos simulados) sin avanzar el reloj. */
async function settle() {
  for (let index = 0; index < 5; index += 1) await Promise.resolve();
}

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

describe("envelope", () => {
  it("completa el envelope en la captura; el componente solo pasa tipo y propiedades", async () => {
    const { service, transport } = createService();
    service.setUser(USER_ID);
    jest.setSystemTime(new Date("2025-01-15T10:30:00.123Z"));

    sidebarClick(service);
    service.flush();
    await settle();

    const [event] = transport.sent[0];
    expect(event).toEqual({
      eventId: expect.stringMatching(UUID_V4),
      timestamp: "2025-01-15T10:30:00.123Z",
      sessionId: expect.stringMatching(UUID_V4),
      userId: USER_ID,
      event_type: "sidebar_item_clicked",
      schemaVersion: "1.0.0",
      requestId: expect.stringMatching(UUID_V4),
      source: "backoffice",
      environment: "development",
      properties: { item_key: "inventory_stock", is_upcoming: false, device_class: "desktop" },
    });
  });

  it("el timestamp es el de la captura, no el del envío", async () => {
    const { service, transport } = createService();
    jest.setSystemTime(new Date("2025-01-15T10:30:00.000Z"));
    sidebarClick(service);
    jest.advanceTimersByTime(FLUSH_INTERVAL_MS);
    await settle();
    expect(transport.sent[0][0].timestamp).toBe("2025-01-15T10:30:00.000Z");
  });

  it("descarta claves fuera del allowlist y solo avisa con su nombre", async () => {
    const { service, transport, warnings } = createService();
    service.track("session_closed", {
      session_duration_s: 60,
      email: "ana@example.com",
    } as never);
    service.flush();
    await settle();

    expect(transport.sent[0][0].properties).toEqual({ session_duration_s: 60 });
    expect(warnings.join(" ")).toContain("email");
    expect(warnings.join(" ")).not.toContain("ana@example.com");
  });

  it("un userId que no es un UUID (p. ej. un email) nunca sale: queda anonymous", async () => {
    const { service, transport } = createService();
    service.setUser("ana@example.com");
    sidebarClick(service);
    service.flush();
    await settle();
    expect(transport.sent[0][0].userId).toBe("anonymous");
  });

  it("los eventos de una llamada a la API comparten su requestId", async () => {
    const { service, transport } = createService();
    const requestId = "0f9e8d7c-6b5a-4c3d-9e1f-2a3b4c5d6e7f";
    service.withRequestId(requestId, () => sidebarClick(service));
    sidebarClick(service);
    service.flush();
    await settle();

    const [correlated, standalone] = transport.sent[0];
    expect(correlated.requestId).toBe(requestId);
    expect(standalone.requestId).not.toBe(requestId);
  });
});

describe("sesión", () => {
  it("mantiene el sessionId en la pestaña y lo rota en el login y en el logout", () => {
    const { service } = createService();
    const initial = service.sessionId();
    expect(service.sessionId()).toBe(initial);

    service.startSession();
    const afterLogin = service.sessionId();
    expect(afterLogin).not.toBe(initial);

    service.endSession();
    expect(service.sessionId()).not.toBe(afterLogin);
  });

  it("mide la edad de la sesión desde el login", () => {
    const { service } = createService();
    expect(service.sessionAgeSeconds()).toBeNull();
    jest.setSystemTime(new Date("2025-01-15T10:00:00.000Z"));
    service.startSession();
    jest.setSystemTime(new Date("2025-01-15T10:25:00.000Z"));
    expect(service.sessionAgeSeconds()).toBe(1500);
  });

  it("funciona aunque el almacenamiento del navegador esté bloqueado", () => {
    const blocked = {
      getItem: () => {
        throw new Error("SecurityError");
      },
      setItem: () => {
        throw new Error("SecurityError");
      },
      removeItem: () => {
        throw new Error("SecurityError");
      },
    };
    const { service } = createService(fakeTransport(), { sessionStore: blocked, loginStore: blocked });
    const id = service.sessionId();
    expect(id).toMatch(UUID_V4);
    expect(service.sessionId()).toBe(id);
  });
});

describe("cola y lotes", () => {
  it("nunca envía de uno en uno: espera 10 s si no se llega a 20 eventos", async () => {
    const { service, transport } = createService();
    sidebarClick(service);
    sidebarClick(service);
    jest.advanceTimersByTime(FLUSH_INTERVAL_MS - 1);
    await settle();
    expect(transport.sent).toHaveLength(0);

    jest.advanceTimersByTime(1);
    await settle();
    expect(transport.sent).toHaveLength(1);
    expect(transport.sent[0]).toHaveLength(2);
  });

  it("envía al llegar a 20 eventos sin esperar al temporizador", async () => {
    const { service, transport } = createService();
    for (let index = 0; index < BATCH_SIZE; index += 1) sidebarClick(service);
    await settle();
    expect(transport.sent).toHaveLength(1);
    expect(transport.sent[0]).toHaveLength(BATCH_SIZE);
    expect(service.pendingEvents).toBe(0);
  });

  it("con la cola llena descarta los eventos más antiguos y los cuenta", () => {
    const { service } = createService(fakeTransport(), { batchSize: 1_000 });
    for (let index = 0; index < MAX_QUEUE_SIZE + 5; index += 1) sidebarClick(service, `item_${index}`);
    expect(service.pendingEvents).toBe(MAX_QUEUE_SIZE);
    expect(service.droppedCount).toBe(5);
  });

  it("sin endpoint configurado no captura nada", () => {
    const { service } = createService(fakeTransport(), { endpoint: null });
    sidebarClick(service);
    expect(service.pendingEvents).toBe(0);
  });
});

describe("reintentos", () => {
  it("reintenta con espera exponencial (1 s, 2 s, 4 s) y descarta el lote tras 3 reintentos", async () => {
    const transport = fakeTransport([503, new Error("sin red"), 503, 503]);
    const { service, warnings } = createService(transport);
    sidebarClick(service);
    service.flush();
    await settle();
    expect(transport.sent).toHaveLength(1);

    jest.advanceTimersByTime(999);
    await settle();
    expect(transport.sent).toHaveLength(1);
    jest.advanceTimersByTime(1);
    await settle();
    expect(transport.sent).toHaveLength(2);

    jest.advanceTimersByTime(2_000);
    await settle();
    expect(transport.sent).toHaveLength(3);

    jest.advanceTimersByTime(4_000);
    await settle();
    expect(transport.sent).toHaveLength(4);

    jest.advanceTimersByTime(60_000);
    await settle();
    expect(transport.sent).toHaveLength(4);
    expect(warnings.at(-1)).toContain("se descartan 1 eventos tras 4 intentos");
  });

  it("deja de reintentar en cuanto la ingesta responde 200", async () => {
    const transport = fakeTransport([500, 200]);
    const { service } = createService(transport);
    sidebarClick(service);
    service.flush();
    await settle();
    jest.advanceTimersByTime(1_000);
    await settle();
    jest.advanceTimersByTime(60_000);
    await settle();
    expect(transport.sent).toHaveLength(2);
  });

  it("no reintenta un 4xx: el lote no cumple el contrato", async () => {
    const transport = fakeTransport([422]);
    const { service, warnings } = createService(transport);
    sidebarClick(service);
    service.flush();
    await settle();
    jest.advanceTimersByTime(60_000);
    await settle();
    expect(transport.sent).toHaveLength(1);
    expect(warnings.at(-1)).toContain("422");
  });
});

describe("flush al ocultar la pestaña", () => {
  it("envía por sendBeacon lo pendiente, incluidos los lotes que esperaban reintento", async () => {
    const transport = fakeTransport([503]);
    const { service } = createService(transport);
    sidebarClick(service, "first");
    service.flush();
    await settle();
    sidebarClick(service, "second");

    service.flushOnHide("hidden");

    expect(transport.beacons).toHaveLength(1);
    const keys = transport.beacons[0].map((event) => (event.properties as { item_key: string }).item_key);
    expect(keys.sort()).toEqual(["first", "second"]);
    jest.advanceTimersByTime(60_000);
    await settle();
    expect(transport.sent).toHaveLength(1); // el reintento ya no se repite por fetch
  });

  it("deja que los oyentes añadan sus últimos eventos antes del beacon", () => {
    const { service, transport } = createService();
    service.onPageHide(() =>
      service.track("session_closed", { session_duration_s: 10 }),
    );
    service.flushOnHide("pagehide");
    expect(transport.beacons[0][0].event_type).toBe("session_closed");
  });

  it("parte lo pendiente en lotes de 20 y recurre a fetch si el navegador rechaza el beacon", async () => {
    // Dos lotes completos fallan y esperan reintento; 3 eventos más siguen en cola.
    const transport = fakeTransport([503, 503]);
    const { service } = createService(transport);
    for (let index = 0; index < 2 * BATCH_SIZE + 3; index += 1) sidebarClick(service);
    await settle();
    transport.beacon = (_endpoint, body) => {
      transport.beacons.push((JSON.parse(body) as { events: TelemetryEvent[] }).events);
      return false;
    };

    service.flushOnHide("hidden");
    await settle();

    expect(transport.beacons.map((batch) => batch.length)).toEqual([20, 20, 3]);
    // Los dos envíos fallidos iniciales y los tres de respaldo con fetch.
    expect(transport.sent.map((batch) => batch.length)).toEqual([20, 20, 20, 20, 3]);
    expect(service.pendingEvents).toBe(0);
  });
});

describe("catálogo frente al esquema aprobado", () => {
  const schema = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../../../docs/telemetry/event-schemas.json"), "utf8"),
  ) as {
    "x-eventTypes": string[];
    definitions: Record<string, { allOf: [unknown, { properties: Record<string, never> }] }>;
  };
  const eventSchema = (type: string) =>
    schema.definitions[type].allOf[1].properties as unknown as {
      source: { enum: string[] };
      schemaVersion: { const: string };
      properties: { properties: Record<string, unknown>; required: string[] };
    };

  it("incluye exactamente los eventos del plan que emite el backoffice", () => {
    const backofficeEvents = schema["x-eventTypes"].filter((type) =>
      eventSchema(type).source.enum.includes("backoffice"),
    );
    expect(Object.keys(EVENT_ALLOWLISTS).sort()).toEqual(backofficeEvents.sort());
  });

  it.each(Object.keys(EVENT_ALLOWLISTS) as BackofficeEventType[])(
    "%s usa el allowlist y la versión del esquema",
    (type) => {
      const definition = eventSchema(type);
      expect([...EVENT_ALLOWLISTS[type]].sort()).toEqual(
        Object.keys(definition.properties.properties).sort(),
      );
      expect(definition.properties.required.sort()).toEqual([...EVENT_ALLOWLISTS[type]].sort());
      expect(definition.schemaVersion.const).toBe("1.0.0");
    },
  );
});
