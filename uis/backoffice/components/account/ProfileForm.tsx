"use client";

import { useState, type FormEvent } from "react";
import { Save } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/components/auth/AuthProvider";
import { requestJson } from "@/lib/api-client";
import { userRoleLabels } from "@/lib/labels";
import type { Profile } from "@/types/auth";

export function ProfileForm() {
  const { user, refreshUser } = useAuth();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setIsSaving(true);
    const formData = new FormData(event.currentTarget);
    try {
      await requestJson<Profile>(
        "/api/profiles/me",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: String(formData.get("name") ?? "").trim(),
            phone: String(formData.get("phone") ?? "").trim(),
            address: String(formData.get("address") ?? "").trim(),
          }),
        },
        "No se pudo actualizar el perfil.",
      );
      await refreshUser();
      setNotice("Perfil actualizado correctamente.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo actualizar el perfil.");
    } finally {
      setIsSaving(false);
    }
  }

  if (!user) return null;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <p className="text-sm font-semibold text-cyan-800">Cuenta</p>
        <h1 className="mt-1 text-2xl font-bold text-slate-950">Perfil personal</h1>
        <p className="mt-1 text-sm text-slate-600">Actualiza los datos de contacto vinculados a tus credenciales.</p>
      </header>

      <section aria-labelledby="credentials-title" className="border-y border-slate-200 bg-white px-5 py-5 sm:rounded-md sm:border">
        <h2 id="credentials-title" className="text-base font-semibold text-slate-900">Credenciales</h2>
        <dl className="mt-4 grid gap-4 sm:grid-cols-2">
          <div><dt className="text-xs font-medium text-slate-500">Email</dt><dd className="mt-1 text-sm text-slate-900">{user.email}</dd></div>
          <div><dt className="text-xs font-medium text-slate-500">Rol</dt><dd className="mt-1 text-sm text-slate-900">{userRoleLabels[user.role]}</dd></div>
        </dl>
        <Link href="/account/change-password" className="mt-4 inline-block text-sm font-semibold text-cyan-800 hover:underline">Cambiar contraseña</Link>
      </section>

      <section aria-labelledby="profile-data-title" className="border-y border-slate-200 bg-white px-5 py-5 sm:rounded-md sm:border">
        <h2 id="profile-data-title" className="text-base font-semibold text-slate-900">Datos de contacto</h2>
        {error ? <p className="mt-4 border-l-4 border-rose-500 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">{error}</p> : null}
        {notice ? <p className="mt-4 border-l-4 border-emerald-500 bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status">{notice}</p> : null}
        <form className="mt-5 grid gap-5 sm:grid-cols-2" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="profile-name" className="text-sm font-medium text-slate-800">Nombre visible</label>
            <input id="profile-name" name="name" defaultValue={user.profile.name ?? ""} autoComplete="name" className="mt-2 block w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100" />
          </div>
          <div>
            <label htmlFor="profile-phone" className="text-sm font-medium text-slate-800">Teléfono</label>
            <input id="profile-phone" name="phone" type="tel" defaultValue={user.profile.phone ?? ""} autoComplete="tel" className="mt-2 block w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100" />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="profile-address" className="text-sm font-medium text-slate-800">Dirección</label>
            <input id="profile-address" name="address" defaultValue={user.profile.address ?? ""} autoComplete="street-address" className="mt-2 block w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100" />
          </div>
          <div className="sm:col-span-2">
            <button type="submit" disabled={isSaving} className="flex h-10 items-center justify-center gap-2 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60">
              <Save aria-hidden="true" className="h-4 w-4" />
              {isSaving ? "Guardando..." : "Guardar cambios"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}