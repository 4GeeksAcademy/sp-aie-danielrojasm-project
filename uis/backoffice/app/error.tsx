"use client";

import { ErrorFallback } from "@/components/ui/ErrorFallback";

interface RouteErrorProps {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}

/** Límite de error de las vistas internas: nunca muestra el mensaje técnico. */
export default function RouteError({ error, unstable_retry }: RouteErrorProps) {
  return (
    <section
      role="alert"
      aria-labelledby="route-error-title"
      className="mx-auto mt-10 max-w-lg rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm"
    >
      <ErrorFallback
        error={error}
        onRetry={() => unstable_retry()}
        headingId="route-error-title"
        title="No se pudo mostrar esta sección"
        description="Se produjo un error inesperado. Puedes reintentarlo o volver al panel de operaciones."
        logLabel="Error de interfaz en el backoffice"
      />
    </section>
  );
}
