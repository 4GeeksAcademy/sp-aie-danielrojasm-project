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
  clearAccessToken,
  getAccessToken,
  requestJson,
  storeAccessToken,
} from "@/lib/api-client";
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
      } catch {
        if (isMounted) setUser(null);
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    void restoreSession();
    return () => {
      isMounted = false;
    };
  }, []);

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
    clearAccessToken();
    setUser(null);
    router.replace("/login");
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: user !== null,
        isLoading,
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