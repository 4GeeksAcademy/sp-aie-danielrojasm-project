/**
 * Funciones puras de apoyo a la telemetría: rutas como plantilla, sección,
 * clase de dispositivo, huella de errores y limitación de ráfagas.
 */
import type { BackofficeSection, DeviceClass } from "@/lib/telemetry-events";

const SAFE_SEGMENT = /^[A-Za-z0-9_\-.]+$/;
const DYNAMIC_SEGMENT = /^(?:\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

/**
 * Plantilla de una ruta: sin origen, query ni fragmento, y con los ids
 * sustituidos por `{id}` (`/api/inventory/products/12?x=1` →
 * `/api/inventory/products/{id}`). Nunca viaja la URL real.
 */
export function routeTemplate(url: string): string {
  let pathname = url;
  try {
    pathname = new URL(url, "http://backoffice.local").pathname;
  } catch {
    pathname = url.split(/[?#]/)[0] ?? "/";
  }
  const segments = pathname
    .split("/")
    .filter(Boolean)
    .map((segment) => (DYNAMIC_SEGMENT.test(segment) || !SAFE_SEGMENT.test(segment) ? "{id}" : segment));
  return `/${segments.join("/")}`.slice(0, 200);
}

/** Plantilla de la página actual del navegador. */
export function currentPageRoute(): string {
  return typeof window === "undefined" ? "/" : routeTemplate(window.location.pathname);
}

const AUTH_ROUTES = new Set(["/login", "/register", "/forgot-password", "/reset-password"]);
const SECTION_PREFIXES: [string, BackofficeSection][] = [
  ["/inventory", "inventory"],
  ["/incidents", "incidents"],
  ["/suppliers", "suppliers"],
  ["/account", "account"],
];

/** Sección del backoffice de una ruta; `null` si no es una vista conocida (404). */
export function sectionForRoute(route: string): BackofficeSection | null {
  if (route === "/") return "dashboard";
  if (AUTH_ROUTES.has(route)) return "auth";
  const match = SECTION_PREFIXES.find(
    ([prefix]) => route === prefix || route.startsWith(`${prefix}/`),
  );
  return match ? match[1] : null;
}

/** Por ancho de viewport, como el `sm`/`md` de Tailwind: < 768 px = móvil. */
export function deviceClass(): DeviceClass {
  return typeof window !== "undefined" && window.innerWidth < 768 ? "mobile" : "desktop";
}

function fnv1a(text: string, seed: number): string {
  let hash = seed >>> 0;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

/** Primer marco del stack como `archivo:línea`, sin origen ni query. */
export function firstStackFrame(stack: string | undefined): string {
  for (const line of (stack ?? "").split("\n")) {
    const match = line.match(/([^\s()@]+?):(\d+):\d+\)?\s*$/);
    if (match) return `${routeTemplate(match[1])}:${match[2]}`;
  }
  return "unknown";
}

/**
 * Huella de un error para agruparlo: 16 hex a partir del nombre y del primer
 * marco del stack. No incluye el mensaje, que puede llevar datos de la UI.
 */
export function errorFingerprint(errorName: string, stack: string | undefined): string {
  const key = `${errorName}|${firstStackFrame(stack)}`;
  return fnv1a(key, 0x811c9dc5) + fnv1a(key, 0x01000193);
}

/** Lee `exp` del JWT sin verificarlo (solo para distinguir caducado de rechazado). */
export function isTokenExpired(token: string, now = Date.now()): boolean {
  try {
    const payload = token.split(".")[1] ?? "";
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const exp = (JSON.parse(json) as { exp?: unknown }).exp;
    return typeof exp === "number" && exp * 1000 <= now;
  } catch {
    return false;
  }
}

export interface ThrottleDecision {
  emit: boolean;
  /** Repeticiones agrupadas desde el último evento emitido con esa clave. */
  suppressed: number;
}

/**
 * Uno por clave cada `windowMs`; las repeticiones intermedias se cuentan y
 * viajan en `suppressed_count` del siguiente evento. `maxPerHour` limita el
 * total de eventos emitidos por hora (p. ej. un error en bucle).
 */
export function createWindowThrottle(windowMs: number, maxPerHour = Infinity, now = () => Date.now()) {
  const lastEmitted = new Map<string, number>();
  const suppressed = new Map<string, number>();
  let hourStart = now();
  let emittedThisHour = 0;

  return (key: string): ThrottleDecision => {
    const current = now();
    if (current - hourStart >= 3_600_000) {
      hourStart = current;
      emittedThisHour = 0;
    }
    const last = lastEmitted.get(key);
    if ((last !== undefined && current - last < windowMs) || emittedThisHour >= maxPerHour) {
      suppressed.set(key, (suppressed.get(key) ?? 0) + 1);
      return { emit: false, suppressed: suppressed.get(key) ?? 0 };
    }
    const count = suppressed.get(key) ?? 0;
    lastEmitted.set(key, current);
    suppressed.delete(key);
    emittedThisHour += 1;
    return { emit: true, suppressed: count };
  };
}
