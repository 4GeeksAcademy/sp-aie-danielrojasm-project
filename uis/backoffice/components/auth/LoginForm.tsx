"use client";

import { useState, type FormEvent } from "react";
import { LogIn } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/components/auth/AuthProvider";

export function LoginForm() {
  const { login } = useAuth();
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    const formData = new FormData(event.currentTarget);

    try {
      await login({
        email: String(formData.get("email") ?? "").trim(),
        password: String(formData.get("password") ?? ""),
      });
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "No se pudo iniciar sesión.",
      );
      setIsSubmitting(false);
    }
  }

  return (
    <form className="space-y-5" onSubmit={handleSubmit}>
      {error ? (
        <p
          id="login-error"
          className="border-l-4 border-rose-500 bg-rose-50 px-4 py-3 text-sm text-rose-800"
          role="alert"
        >
          {error}
        </p>
      ) : null}

      <div>
        <label htmlFor="login-email" className="text-sm font-medium text-slate-800">
          Email
        </label>
        <input
          id="login-email"
          name="email"
          type="email"
          autoComplete="email"
          required
          aria-describedby={error ? "login-error" : undefined}
          className="mt-2 block w-full rounded-md border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100"
        />
      </div>

      <div>
        <label htmlFor="login-password" className="text-sm font-medium text-slate-800">
          Contraseña
        </label>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          aria-describedby={error ? "login-error" : undefined}
          className="mt-2 block w-full rounded-md border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100"
        />
        <Link href="/forgot-password" className="mt-2 block text-right text-sm font-medium text-cyan-800 hover:underline">
          ¿Olvidaste tu contraseña?
        </Link>
      </div>

      <button
        type="submit"
        disabled={isSubmitting}
        className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <LogIn aria-hidden="true" className="h-4 w-4" />
        {isSubmitting ? "Iniciando sesión..." : "Iniciar sesión"}
      </button>
    </form>
  );
}