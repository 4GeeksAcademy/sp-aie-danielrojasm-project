import type { ReactNode } from "react";

interface InventoryPageHeaderProps {
  title: string;
  description: string;
  /** Acciones a la derecha del título (enlaces a otras vistas). */
  actions?: ReactNode;
}

export function InventoryPageHeader({ title, description, actions }: InventoryPageHeaderProps) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">
          Almacén · Inventario
        </p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">{title}</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-600">{description}</p>
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}
