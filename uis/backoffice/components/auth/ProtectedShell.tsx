"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { useAuth } from "@/components/auth/AuthProvider";

const publicRoutes = new Set(["/login", "/register", "/forgot-password", "/reset-password"]);
const guestOnlyRoutes = new Set(["/login", "/register"]);

export function ProtectedShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isLoading, sessionError, retrySession, logout } = useAuth();
  const isPublicRoute = publicRoutes.has(pathname);
  const isGuestOnlyRoute = guestOnlyRoutes.has(pathname);

  useEffect(() => {
    if (isLoading || sessionError) return;
    if (!isPublicRoute && !isAuthenticated) router.replace("/login");
    if (isGuestOnlyRoute && isAuthenticated) router.replace("/");
  }, [isAuthenticated, isLoading, sessionError, isPublicRoute, isGuestOnlyRoute, router]);

  if (isLoading || (isGuestOnlyRoute && isAuthenticated)) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-sm text-slate-300">
        Verificando sesión...
      </div>
    );
  }

  if (isPublicRoute) return children;
  if (sessionError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
        <div
          role="alert"
          className="w-full max-w-md rounded-xl bg-white p-6 text-center shadow-xl"
        >
          <h1 className="text-lg font-semibold text-slate-950">
            No pudimos comprobar tu sesión
          </h1>
          <p className="mt-2 text-sm text-slate-600">{sessionError}</p>
          <div className="mt-5 flex flex-wrap justify-center gap-3">
            <button
              type="button"
              onClick={retrySession}
              className="h-10 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800"
            >
              Reintentar
            </button>
            <button
              type="button"
              onClick={logout}
              className="h-10 rounded-md border border-slate-300 px-4 text-sm font-semibold text-slate-800 hover:bg-slate-50"
            >
              Ir al inicio de sesión
            </button>
          </div>
        </div>
      </div>
    );
  }
  if (!isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-sm text-slate-300">
        Redirigiendo al acceso...
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}