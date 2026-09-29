/**
 * Autenticación en el cliente (`lib/api-client.ts`): guardado del token,
 * cabecera Authorization, cierre de sesión ante 401 y mensajes de error.
 */
import {
  ApiError,
  NETWORK_ERROR_STATUS,
  apiFetch,
  clearAccessToken,
  getAccessToken,
  getUserMessage,
  requestJson,
  storeAccessToken,
} from "@/lib/api-client";

const TOKEN_KEY = "trackflow_access_token";

// Entorno node: se simula lo mínimo de `window` que usa el cliente.
function installWindow(pathname = "/incidents") {
  const store = new Map<string, string>();
  const location = { pathname, assign: jest.fn() };
  Object.assign(globalThis, {
    window: {
      localStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => void store.set(key, value),
        removeItem: (key: string) => void store.delete(key),
      },
      location,
    },
  });
  return location;
}

function mockFetch(response: Response | Error) {
  const fetchMock = jest.fn(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  );
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Captura el ApiError rechazado para poder inspeccionar status, message y body.
function rejection(promise: Promise<unknown>): Promise<ApiError> {
  return promise.then(
    () => {
      throw new Error("Se esperaba un rechazo");
    },
    (error: ApiError) => error,
  );
}

beforeEach(() => installWindow());
afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
  jest.restoreAllMocks();
});

describe("almacenamiento del token", () => {
  it("guarda, lee y borra el token de acceso", () => {
    storeAccessToken("abc");
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe("abc");
    expect(getAccessToken()).toBe("abc");
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });

  it("no falla en el servidor, donde no existe window", () => {
    // Next ejecuta los módulos también en SSR.
    delete (globalThis as { window?: unknown }).window;
    expect(getAccessToken()).toBeNull();
    expect(() => clearAccessToken()).not.toThrow();
  });
});

describe("apiFetch", () => {
  it("envía el token como Bearer cuando hay sesión", async () => {
    storeAccessToken("abc");
    const fetchMock = mockFetch(json({}, 200));
    await apiFetch("/auth/me");
    const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer abc");
  });

  it("no envía Authorization sin sesión", async () => {
    const fetchMock = mockFetch(json({}, 200));
    await apiFetch("/auth/login", { method: "POST" });
    const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
  });

  it("ante un 401 borra el token y redirige al login (token caducado)", async () => {
    const location = installWindow("/incidents");
    storeAccessToken("caducado");
    mockFetch(json({ detail: "Token caducado" }, 401));
    await apiFetch("/auth/me");
    expect(getAccessToken()).toBeNull();
    expect(location.assign).toHaveBeenCalledWith("/login");
  });

  it("no vuelve a redirigir si ya está en /login", async () => {
    // Evita un bucle de recargas cuando el propio login devuelve 401.
    const location = installWindow("/login");
    mockFetch(json({ detail: "Credenciales incorrectas" }, 401));
    await apiFetch("/auth/login");
    expect(location.assign).not.toHaveBeenCalled();
  });

  it("convierte un fallo de red en ApiError con estado 0 y mensaje legible", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    const error = await rejection(apiFetch("/auth/me"));
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(NETWORK_ERROR_STATUS);
    expect(error.message).not.toContain("Failed to fetch");
  });
});

describe("requestJson", () => {
  it("devuelve el cuerpo JSON en una respuesta correcta", async () => {
    mockFetch(json({ email: "ana@example.com" }, 200));
    await expect(requestJson("/auth/me")).resolves.toEqual({ email: "ana@example.com" });
  });

  it("devuelve undefined en un 204", async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(requestJson("/users/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("reutiliza el detail en español de un 4xx", async () => {
    mockFetch(json({ detail: "El email ya está registrado." }, 409));
    await expect(requestJson("/users")).rejects.toMatchObject({
      status: 409,
      message: "El email ya está registrado.",
    });
  });

  it("usa un mensaje genérico para errores de validación por campo", async () => {
    mockFetch(json({ detail: [{ loc: ["body", "password"], msg: "too short" }] }, 422));
    const error = await rejection(requestJson("/users"));
    // El texto técnico de Pydantic no llega al usuario, pero el cuerpo sí queda disponible.
    expect(error.message).not.toContain("too short");
    expect(error.body?.detail).toEqual([{ loc: ["body", "password"], msg: "too short" }]);
  });

  it("oculta el detalle de un 5xx", async () => {
    mockFetch(json({ detail: "Traceback: KeyError JWT_SECRET_KEY" }, 500));
    const error = await rejection(requestJson("/auth/me"));
    expect(error.status).toBe(500);
    expect(error.message).not.toContain("JWT_SECRET_KEY");
  });

  it("usa el fallback si el error no trae JSON", async () => {
    mockFetch(new Response("<html>Bad gateway</html>", { status: 404 }));
    await expect(requestJson("/x", {}, "No se encontró.")).rejects.toMatchObject({
      message: "No se encontró.",
    });
  });

  it("rechaza con ApiError una respuesta 200 que no es JSON", async () => {
    mockFetch(new Response("no es json", { status: 200 }));
    await expect(requestJson("/auth/me")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("getUserMessage", () => {
  it("muestra el mensaje de un ApiError", () => {
    expect(getUserMessage(new ApiError("Sesión caducada", 401), "fallback")).toBe(
      "Sesión caducada",
    );
  });

  it("no expone errores de programación", () => {
    expect(getUserMessage(new TypeError("x is undefined"), "Algo falló")).toBe("Algo falló");
  });
});
