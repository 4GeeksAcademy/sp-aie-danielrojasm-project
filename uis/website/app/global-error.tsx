"use client";

import { ErrorFallback } from "@/components/ui/ErrorFallback";
import "./globals.css";

interface GlobalErrorProps {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}

export default function GlobalError({ error, unstable_retry }: GlobalErrorProps) {
  return (
    <html lang="es">
      <body className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-white">
        <title>Error | TrackFlow</title>
        <main role="alert" className="max-w-xl text-center">
          <ErrorFallback
            error={error}
            onRetry={() => unstable_retry()}
            title="TrackFlow no está disponible ahora mismo"
            description="Se produjo un error inesperado. Vuelve a intentarlo en unos instantes."
            logLabel="Error crítico en la web"
          />
        </main>
      </body>
    </html>
  );
}
