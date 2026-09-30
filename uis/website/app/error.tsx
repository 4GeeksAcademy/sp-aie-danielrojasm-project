"use client";

import { ErrorFallback } from "@/components/ui/ErrorFallback";

interface RouteErrorProps {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}

export default function RouteError({ error, unstable_retry }: RouteErrorProps) {
  return (
    <section
      role="alert"
      aria-labelledby="route-error-title"
      className="mx-auto max-w-xl px-4 py-24 text-center"
    >
      <ErrorFallback
        error={error}
        onRetry={() => unstable_retry()}
        headingId="route-error-title"
        title="Algo no ha ido bien"
        description="No pudimos mostrar esta página. Vuelve a intentarlo o regresa al inicio."
        logLabel="Error de interfaz en la web"
      />
    </section>
  );
}
