"use client";

import { ErrorFallback } from "@/components/ui/ErrorFallback";
import "./globals.css";

interface GlobalErrorProps {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}

/** Sustituye al layout raíz si este falla (p. ej. el proveedor de sesión). */
export default function GlobalError({ error, unstable_retry }: GlobalErrorProps) {
  return (
    <html lang="es">
      <body className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-900">
        <title>Error | Backoffice TrackFlow</title>
        <main role="alert" className="w-full max-w-md rounded-xl bg-white p-6 text-center shadow-xl">
          <ErrorFallback
            error={error}
            onRetry={() => unstable_retry()}
            title="El backoffice no se pudo cargar"
            description="Se produjo un error inesperado. Reintenta o vuelve al panel de operaciones."
            logLabel="Error crítico en el backoffice"
          />
        </main>
      </body>
    </html>
  );
}
