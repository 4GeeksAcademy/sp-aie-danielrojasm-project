"use client";

import { useState, type FormEvent } from "react";
import { Mail } from "lucide-react";
import { requestJson } from "@/lib/api-client";

export function ForgotPasswordForm() {
  const [sent, setSent] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || sent) return;
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    setPending(true);
    setError("");
    try {
      await requestJson("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      setSent(true);
    } catch {
      setError("No se pudo procesar la solicitud. Inténtalo de nuevo.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="space-y-5" onSubmit={handleSubmit}>
      {sent ? <p role="status" className="border-l-4 border-emerald-500 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">Si esa dirección está registrada, recibirás un enlace en breve.</p> : null}
      {error ? <p id="forgot-error" role="alert" className="border-l-4 border-rose-500 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</p> : null}
      <div>
        <label htmlFor="forgot-email" className="text-sm font-medium text-slate-800">Email</label>
        <input id="forgot-email" name="email" type="email" autoComplete="email" required disabled={sent || pending} aria-describedby={error ? "forgot-error" : undefined} className="mt-2 block w-full rounded-md border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100 disabled:opacity-60" />
      </div>
      <button type="submit" disabled={sent || pending} className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60">
        <Mail aria-hidden="true" className="h-4 w-4" />{pending ? "Enviando..." : "Enviar enlace"}
      </button>
    </form>
  );
}