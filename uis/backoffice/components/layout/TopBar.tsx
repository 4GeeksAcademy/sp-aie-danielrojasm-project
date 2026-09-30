"use client";

import Link from "next/link";
import { LogOut, UserRound } from "lucide-react";
import { useAuth } from "@/components/auth/AuthProvider";

export function TopBar() {
  const { user, logout } = useAuth();

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-6 py-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">
          Operaciones de almacén · Los Ángeles y Zaragoza
        </p>
        <p className="text-sm text-slate-500">
          Responsable: Ana Whitfield, Directora de Operaciones de Almacén
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Link
          href="/account/profile"
          className="flex h-10 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm text-slate-700 hover:bg-slate-50"
        >
          <UserRound aria-hidden="true" className="h-4 w-4" />
          {/* En móvil solo se ve el icono, pero el nombre sigue siendo el texto del enlace. */}
          <span className="sr-only sm:not-sr-only">{user?.profile?.name || user?.email || "Mi cuenta"}</span>
        </Link>
        <button
          type="button"
          onClick={logout}
          title="Cerrar sesión"
          className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-950"
        >
          <LogOut aria-hidden="true" className="h-4 w-4" />
          <span className="sr-only">Cerrar sesión</span>
        </button>
      </div>
    </header>
  );
}
