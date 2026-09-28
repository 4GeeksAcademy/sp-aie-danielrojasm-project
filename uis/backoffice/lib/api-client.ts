const TOKEN_STORAGE_KEY = "trackflow_access_token";

interface ApiErrorBody {
  detail?: string | { loc?: (string | number)[]; msg?: string }[];
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

export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(input, { ...init, headers });
  if (response.status === 401) redirectToLogin();
  return response;
}

async function getApiError(
  response: Response,
  fallback: string,
): Promise<{ body: ApiErrorBody | null; message: string }> {
  const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
  if (typeof body?.detail === "string") return { body, message: body.detail };
  if (Array.isArray(body?.detail)) {
    const messages = body.detail.flatMap((item) => item.msg ?? []);
    if (messages.length > 0) return { body, message: messages.join(" ") };
  }
  return { body, message: fallback };
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
  return (await response.json()) as T;
}