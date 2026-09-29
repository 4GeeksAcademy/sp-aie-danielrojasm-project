"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Save } from "lucide-react";
import { getUserMessage, requestJson } from "@/lib/api-client";

export function ChangePasswordForm() {
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const formData = new FormData(form);
    const newPassword = String(formData.get("new_password") ?? "");
    if (newPassword !== formData.get("confirmation")) {
      setError("Las contraseñas no coinciden.");
      setNotice("");
      return;
    }
    setPending(true);
    setError("");
    setNotice("");
    try {
      await requestJson("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: formData.get("current_password"), new_password: newPassword }),
      });
      form.reset();
      setNotice("Contraseña actualizada correctamente.");
    } catch (requestError) {
      setError(getUserMessage(requestError, "No se pudo actualizar la contraseña. Inténtalo de nuevo."));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header><p className="text-sm font-semibold text-cyan-800">Cuenta</p><h1 className="mt-1 text-2xl font-bold text-slate-950">Cambiar contraseña</h1></header>
      <section aria-labelledby="change-password-title" className="border-y border-slate-200 bg-white px-5 py-5 sm:rounded-md sm:border">
        <h2 id="change-password-title" className="text-base font-semibold text-slate-900">Credenciales</h2>
        {error ? <p id="change-error" role="alert" className="mt-4 border-l-4 border-rose-500 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</p> : null}
        {notice ? <p role="status" className="mt-4 border-l-4 border-emerald-500 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p> : null}
        <form className="mt-5 space-y-5" onSubmit={handleSubmit}>
          <div><label htmlFor="current-password" className="text-sm font-medium text-slate-800">Contraseña actual</label><input id="current-password" name="current_password" type="password" autoComplete="current-password" required aria-describedby={error ? "change-error" : undefined} className="mt-2 block w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100" /></div>
          <div><label htmlFor="new-password" className="text-sm font-medium text-slate-800">Nueva contraseña</label><input id="new-password" name="new_password" type="password" autoComplete="new-password" minLength={8} maxLength={72} required aria-describedby={error ? "change-error" : undefined} className="mt-2 block w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100" /></div>
          <div><label htmlFor="confirm-password" className="text-sm font-medium text-slate-800">Confirmar contraseña</label><input id="confirm-password" name="confirmation" type="password" autoComplete="new-password" minLength={8} maxLength={72} required aria-describedby={error ? "change-error" : undefined} className="mt-2 block w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100" /></div>
          <div className="flex flex-wrap items-center gap-5"><button type="submit" disabled={pending} className="flex h-10 items-center gap-2 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"><Save aria-hidden="true" className="h-4 w-4" />{pending ? "Guardando..." : "Guardar contraseña"}</button><Link href="/account/profile" className="text-sm font-medium text-cyan-800 hover:underline">Volver al perfil</Link></div>
        </form>
      </section>
    </div>
  );
}