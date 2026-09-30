/**
 * Eventos técnicos transversales (errores y sesión) que se capturan en
 * `api-client`, en los límites de error y en los oyentes globales. Aplican la
 * limitación de ráfagas del plan (sección 9) y siempre pasan por `track()`.
 */
import { abandonActiveInventoryForm, hasUnsavedInventoryForm } from "@/lib/inventory-telemetry";
import { track, telemetrySessionAgeSeconds, withTelemetryRequestId } from "@/lib/telemetry";
import type { BackofficeEventProperties, HttpMethod } from "@/lib/telemetry-events";
import {
  createWindowThrottle,
  currentPageRoute,
  errorFingerprint,
  isTokenExpired,
  routeTemplate,
} from "@/lib/telemetry-helpers";

const HTTP_METHODS: readonly HttpMethod[] = ["GET", "POST", "PUT", "PATCH", "DELETE"];

// Con la API caída cada vista reintenta: uno por ruta y estado cada 30 s.
const apiFailureThrottle = createWindowThrottle(30_000);
// Un error de render se repite en bucle: uno por huella cada 60 s, 20 por hora.
const frontendErrorThrottle = createWindowThrottle(60_000, 20);

export function reportApiCallFailure(
  url: string,
  method: string | undefined,
  requestId: string,
  statusCode: number,
  failureType: BackofficeEventProperties["api_call_failed"]["failure_type"],
): void {
  const apiRoute = routeTemplate(url);
  const decision = apiFailureThrottle(`${apiRoute}|${statusCode}`);
  if (!decision.emit) return;
  const upper = (method ?? "GET").toUpperCase();
  withTelemetryRequestId(requestId, () =>
    track("api_call_failed", {
      api_route: apiRoute,
      http_method: HTTP_METHODS.find((item) => item === upper) ?? "GET",
      status_code: statusCode,
      failure_type: failureType,
      page_route: currentPageRoute(),
      suppressed_count: decision.suppressed,
    }),
  );
}

/** 401 con un token guardado: la sesión caducó o el token dejó de valer. */
export function reportSessionExpired(token: string, requestId: string): void {
  const hadUnsavedForm = hasUnsavedInventoryForm();
  withTelemetryRequestId(requestId, () =>
    track("session_expired", {
      cause: isTokenExpired(token) ? "token_expired" : "token_invalid",
      route: currentPageRoute(),
      session_age_s: telemetrySessionAgeSeconds() ?? 0,
      had_unsaved_form: hadUnsavedForm,
    }),
  );
  abandonActiveInventoryForm("session_expired");
}

type ErrorBoundary = BackofficeEventProperties["frontend_error_captured"]["boundary"];

/** Error de cliente: solo nombre, `digest` de Next y huella; nunca el mensaje ni el stack. */
export function reportFrontendError(error: unknown, boundary: ErrorBoundary): void {
  const isError = error instanceof Error;
  // Sin objeto de error (script de otro origen) o rechazos con un valor que no es Error.
  const kind = error === null || error === undefined ? "UnknownError" : typeof error;
  const errorName = (isError ? error.name : kind).slice(0, 80) || "Error";
  const fingerprint = errorFingerprint(errorName, isError ? error.stack : undefined);
  const decision = frontendErrorThrottle(fingerprint);
  if (!decision.emit) return;
  const digest = isError ? (error as Error & { digest?: unknown }).digest : undefined;
  track("frontend_error_captured", {
    boundary,
    page_route: currentPageRoute(),
    error_name: errorName,
    error_digest: typeof digest === "string" ? digest.slice(0, 64) : null,
    fingerprint,
    suppressed_count: decision.suppressed,
  });
}
