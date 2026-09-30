"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  clearAccessToken,
  getAccessToken,
  getUserMessage,
  requestJson,
  storeAccessToken,
} from "@/lib/api-client";
import {
  endTelemetrySession,
  setTelemetryUser,
  startTelemetrySession,
  telemetrySessionAgeSeconds,
  track,
} from "@/lib/telemetry";
import type {
  AuthUser,
  LoginCredentials,
  RegistrationData,
  TokenResponse,
} from "@/types/auth";

interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  /** Fallo al restaurar la sesión que no es un 401 (red, 5xx): se puede reintentar. */
  sessionError: string | null;
  retrySession: () => void;
  login: (credentials: LoginCredentials) => Promise<void>;
  register: (data: RegistrationData) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function fetchCurrentUser(): Promise<AuthUser> {
  return requestJson<AuthUser>(
    "/api/auth/me",
    {},
    "No se pudo recuperar la sesión.",
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [sessionAttempt, setSessionAttempt] = useState(0);

  useEffect(() => {
    let isMounted = true;

    async function restoreSession() {
      if (!getAccessToken()) {
        if (isMounted) setIsLoading(false);
        return;
      }

      try {
        const currentUser = await fetchCurrentUser();
        if (isMounted) setUser(currentUser);
      } catch (error) {
        if (!isMounted) return;
        setUser(null);
        // 401: el token no vale y apiFetch ya redirige a /login. Cualquier otro
        // fallo no significa que la sesión haya caducado: se informa y se
        // conserva el token para poder reintentar.
        if (!(error instanceof ApiError && error.status === 401)) {
          setSessionError(
            getUserMessage(error, "No se pudo comprobar tu sesión. Inténtalo de nuevo."),
          );
        }
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    void restoreSession();
    return () => {
      isMounted = false;
    };
  }, [sessionAttempt]);

  // `userId` de los eventos: el id del usuario (nunca el email), o `anonymous`.
  useEffect(() => {
    setTelemetryUser(user?.id ?? null);
  }, [user]);

  function retrySession() {
    setSessionError(null);
    setIsLoading(true);
    setSessionAttempt((attempt) => attempt + 1);
  }

  async function refreshUser() {
    const currentUser = await fetchCurrentUser();
    setUser(currentUser);
  }

  async function login(credentials: LoginCredentials) {
    clearAccessToken();
    const token = await requestJson<TokenResponse>(
      "/api/auth/login",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(credentials),
      },
      "No se pudo iniciar sesión.",
    );
    storeAccessToken(token.access_token);
    startTelemetrySession();
    await refreshUser();
    router.replace("/");
  }

  async function register(data: RegistrationData) {
    await requestJson(
      "/api/users",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      },
      "No se pudo crear la cuenta.",
    );
    await login({ email: data.email, password: data.password });
  }

  function logout() {
    // ¿Se cierra sesión en los puestos compartidos o se deja caducar?
    track("session_closed", { session_duration_s: telemetrySessionAgeSeconds() ?? 0 });
    endTelemetrySession();
    clearAccessToken();
    setUser(null);
    setSessionError(null);
    router.replace("/login");
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: user !== null,
        isLoading,
        sessionError,
        retrySession,
        login,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth debe usarse dentro de AuthProvider");
  return context;
}