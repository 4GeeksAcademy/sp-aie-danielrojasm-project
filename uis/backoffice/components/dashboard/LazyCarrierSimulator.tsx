"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import type { CarrierSimulatorProps } from "@/components/dashboard/CarrierSimulator";

function SimulatorSkeleton() {
  return (
    <div aria-busy="true" className="grid gap-6 xl:grid-cols-[280px_1fr]">
      <p className="sr-only" role="status">
        Cargando el simulador…
      </p>
      <div className="h-80 animate-pulse rounded-md bg-slate-100" />
      <div className="h-80 animate-pulse rounded-md bg-slate-100" />
    </div>
  );
}

// next/dynamic solo divide el código desde un Client Component; desde la página
// (Server Component) el simulador iría en el JS inicial del dashboard.
const CarrierSimulator = dynamic(
  () => import("@/components/dashboard/CarrierSimulator").then((mod) => mod.CarrierSimulator),
  { loading: SimulatorSkeleton },
);

/**
 * El simulador está bajo los KPIs y el inventario. En móvil queda a ~2.000 px
 * (2,4 pantallas) y su código (formulario, scoring y tabla de evaluación) solo
 * se pide al acercarse con el scroll; en escritorio está en el pliegue y se
 * pide nada más montar, pero en un chunk aparte que no retrasa el resto.
 */
export function LazyCarrierSimulator(props: CarrierSimulatorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isNearViewport, setIsNearViewport] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setIsNearViewport(true);
          observer.disconnect();
        }
      },
      // Margen para que el chunk llegue antes de que el usuario vea el hueco.
      { rootMargin: "400px 0px" },
    );
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={containerRef}>
      {isNearViewport ? <CarrierSimulator {...props} /> : <SimulatorSkeleton />}
    </div>
  );
}
