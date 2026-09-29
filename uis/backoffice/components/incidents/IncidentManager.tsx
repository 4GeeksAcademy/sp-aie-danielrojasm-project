"use client";

import { useState } from "react";
import { IncidentBoard } from "@/components/incidents/IncidentBoard";
import { IncidentSummaryPanel } from "@/components/incidents/IncidentSummaryPanel";

/** Panel de incidencias: resumen y listado cargan y fallan de forma independiente. */
export function IncidentManager() {
  const [summaryVersion, setSummaryVersion] = useState(0);

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">
          Incidencias · Gestor centralizado
        </p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">Panel de incidencias</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-600">
          Seguimiento de las incidencias de clientes, sedes y equipos internos de
          Los Ángeles y Zaragoza, con su estado en tiempo real.
        </p>
      </header>
      <IncidentSummaryPanel refreshKey={summaryVersion} />
      <IncidentBoard onChanged={() => setSummaryVersion((value) => value + 1)} />
    </div>
  );
}
