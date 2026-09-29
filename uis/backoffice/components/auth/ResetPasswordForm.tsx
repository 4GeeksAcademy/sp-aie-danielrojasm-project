"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { KeyRound } from "lucide-react";
import { clearAccessToken, requestJson } from "@/lib/api-client";

export function ResetPasswordForm({ token }: { token: string | undefined }) {
  const [error, setError] = useState(token ? "" : "El enlace de restablecimiento no es válido.");
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || pending) return;
    const formData = new FormData(event.currentTarget);
    const password = String(formData.get("password") ?? "");
    if (password !== formData.get("confirmation")) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    setError("");
    setPending(true);
    try {
      await requestJson("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      clearAccessToken();
      window.location.replace("/login?reset=success");
    } catch {
      setError("El enlace es inválido, ha caducado o ya se ha utilizado. Solicita uno nuevo.");
      setPending(false);
    }
  }

  return (
    <form className="space-y-5" onSubmit={handleSubmit}>
      {error ? <p id="reset-error" role="alert" className="border-l-4 border-rose-500 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error} <Link href="/forgot-password" className="font-semibold underline">Volver a recuperar contraseña</Link></p> : null}
      <div>
        <label htmlFor="reset-password" className="text-sm font-medium text-slate-800">Nueva contraseña</label>
        <input id="reset-password" name="password" type="password" autoComplete="new-password" minLength={8} maxLength={72} required disabled={!token || pending} aria-describedby={error ? "reset-error" : undefined} className="mt-2 block w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100" />
      </div>
      <div>
        <label htmlFor="reset-confirmation" className="text-sm font-medium text-slate-800">Confirmar contraseña</label>
        <input id="reset-confirmation" name="confirmation" type="password" autoComplete="new-password" minLength={8} maxLength={72} required disabled={!token || pending} aria-describedby={error ? "reset-error" : undefined} className="mt-2 block w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100" />
      </div>
      <button type="submit" disabled={!token || pending} className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"><KeyRound aria-hidden="true" className="h-4 w-4" />{pending ? "Guardando..." : "Restablecer contraseña"}</button>
    </form>
  );
}