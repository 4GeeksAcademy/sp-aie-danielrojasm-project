import { createUuid, endTelemetrySession, telemetrySessionId } from "@/lib/telemetry";
import { reportApiCallFailure, reportSessionExpired } from "@/lib/telemetry-reporters";

const TOKEN_STORAGE_KEY = "trackflow_access_token";

interface ApiErrorBody {
  detail?: string | { loc?: (string | number)[]; msg?: string }[];
  /** Errores por campo (400 de `/api/incidents`). */
  errors?: { field: string; message: string }[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: ApiErrorBody | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function storeAccessToken(token: string): void {
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearAccessToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

function redirectToLogin(): void {
  clearAccessToken();
  if (window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

/** Estado 0: la petición no llegó a completarse (sin red, CORS, API caída). */
export const NETWORK_ERROR_STATUS = 0;

const NETWORK_ERROR_MESSAGE =
  "No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.";
const SERVER_ERROR_MESSAGE =
  "El servicio no está disponible en este momento. Inténtalo de nuevo en unos minutos.";
const INVALID_RESPONSE_MESSAGE =
  "El servidor respondió con datos que no se pudieron interpretar. Inténtalo de nuevo.";
const VALIDATION_ERROR_MESSAGE = "Revisa los datos del formulario e inténtalo de nuevo.";

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  return input instanceof URL ? input.href : input.url;
}

export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // Correlación: la API registra este id en su log y en sus eventos.
  const requestId = createUuid();
  headers.set("X-Request-Id", requestId);
  const sessionId = telemetrySessionId();
  if (sessionId) headers.set("X-Session-Id", sessionId);

  let response: Response;
  try {
    response = await fetch(input, { ...init, headers });
  } catch {
    // fetch solo rechaza por fallos de red; su mensaje ("Failed to fetch")
    // no es útil para el usuario.
    reportApiCallFailure(requestUrl(input), init.method, requestId, NETWORK_ERROR_STATUS, "network");
    throw new ApiError(NETWORK_ERROR_MESSAGE, NETWORK_ERROR_STATUS);
  }
  if (response.status >= 500) {
    reportApiCallFailure(requestUrl(input), init.method, requestId, response.status, "server_error");
  }
  if (response.status === 401) {
    // Con token guardado, el 401 es una sesión que caduca; sin él, un login fallido.
    if (token) {
      reportSessionExpired(token, requestId);
      endTelemetrySession();
    }
    redirectToLogin();
  }
  return response;
}

function reportInvalidResponse(response: Response, init: RequestInit, input: RequestInfo | URL): void {
  reportApiCallFailure(
    requestUrl(input),
    init.method,
    response.headers.get("X-Request-Id") ?? createUuid(),
    response.status,
    "invalid_response",
  );
}

/**
 * Mensaje legible para una respuesta de error. Solo se reutiliza el `detail`
 * de texto de los 4xx (la API los redacta en español para el usuario); los
 * errores de validación por campo y los 5xx usan textos propios.
 */
async function getApiError(
  response: Response,
  fallback: string,
): Promise<{ body: ApiErrorBody | null; message: string }> {
  let body: ApiErrorBody | null = null;
  try {
    body = (await response.json()) as ApiErrorBody | null;
  } catch {
    body = null;
  }
  if (response.status >= 500) return { body, message: SERVER_ERROR_MESSAGE };
  if (typeof body?.detail === "string" && body.detail.trim()) {
    return { body, message: body.detail };
  }
  if (Array.isArray(body?.detail) || Array.isArray(body?.errors)) {
    return { body, message: VALIDATION_ERROR_MESSAGE };
  }
  return { body, message: fallback };
}

async function parseJson<T>(
  response: Response,
  init: RequestInit,
  input: RequestInfo | URL,
): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    reportInvalidResponse(response, init, input);
    throw new ApiError(INVALID_RESPONSE_MESSAGE, response.status);
  }
}

export async function requestJson<T>(
  input: RequestInfo | URL,
  init: RequestInit = {},
  fallbackError = "No se pudo completar la solicitud.",
): Promise<T> {
  const response = await apiFetch(input, init);
  if (!response.ok) {
    const error = await getApiError(response, fallbackError);
    throw new ApiError(error.message, response.status, error.body);
  }
  if (response.status === 204) return undefined as T;
  return parseJson<T>(response, init, input);
}

export async function requestBlob(
  input: RequestInfo | URL,
  init: RequestInit = {},
  fallbackError = "No se pudo descargar el fichero.",
): Promise<Blob> {
  const response = await apiFetch(input, init);
  if (!response.ok) {
    const error = await getApiError(response, fallbackError);
    throw new ApiError(error.message, response.status, error.body);
  }
  try {
    return await response.blob();
  } catch {
    reportInvalidResponse(response, init, input);
    throw new ApiError(INVALID_RESPONSE_MESSAGE, response.status);
  }
}

/**
 * Texto seguro para mostrar al usuario a partir de cualquier error capturado.
 * Solo los `ApiError` llevan mensajes redactados para la UI; cualquier otro
 * error (de programación, de parseo...) se sustituye por `fallback`.
 */
export function getUserMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}
