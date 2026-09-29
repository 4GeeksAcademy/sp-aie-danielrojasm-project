import Link from "next/link";
import type { ReactNode } from "react";

interface AuthScreenProps {
  title: string;
  description: string;
  alternateText: string;
  alternateLabel: string;
  alternateHref: "/login" | "/register";
  children: ReactNode;
}

export function AuthScreen({
  title,
  description,
  alternateText,
  alternateLabel,
  alternateHref,
  children,
}: AuthScreenProps) {
  return (
    <main className="grid min-h-screen bg-white lg:grid-cols-[minmax(20rem,0.75fr)_minmax(30rem,1.25fr)]">
      <section
        aria-labelledby="auth-brand-title"
        className="flex min-h-48 flex-col justify-between bg-slate-950 px-6 py-8 text-white sm:px-10 lg:min-h-screen lg:px-12 lg:py-12"
      >
        <div className="flex items-center gap-3">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-md bg-cyan-300 text-sm font-black text-slate-950">
            TF
          </span>
          <div>
            <p id="auth-brand-title" className="font-bold">TrackFlow Tech</p>
            <p className="text-xs text-slate-400">Backoffice interno</p>
          </div>
        </div>
        <div className="max-w-md">
          <p className="text-sm font-semibold text-cyan-300">Operación conectada</p>
          <p className="mt-2 text-2xl font-semibold leading-tight sm:text-3xl">
            Una sesión segura para trabajar con datos logísticos sensibles.
          </p>
        </div>
      </section>

      <section
        aria-labelledby="auth-form-title"
        className="flex items-center px-6 py-10 sm:px-10 lg:px-16"
      >
        <div className="mx-auto w-full max-w-md">
          <h1 id="auth-form-title" className="text-3xl font-bold text-slate-950">
            {title}
          </h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
          <div className="mt-8">{children}</div>
          <p className="mt-7 border-t border-slate-200 pt-5 text-sm text-slate-600">
            {alternateText}{" "}
            <Link
              href={alternateHref}
              className="font-semibold text-cyan-800 underline-offset-4 hover:underline"
            >
              {alternateLabel}
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}