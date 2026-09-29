"use client";

import { useState } from "react";
import {
  binarySearchProductByWeight,
  findProductBySKU,
  findShipmentById,
} from "@trackflow/logic/utils/search";
import type { Product, Shipment } from "@trackflow/logic/types/models";
import { Badge } from "@/components/ui/Panel";
import {
  countryLabels,
  priorityLabels,
  shipmentStatusLabels,
  warehouseLabels,
} from "@/lib/labels";

type LookupMode = "shipment" | "sku" | "weight";

interface RecordLookupProps {
  products: Product[];
  /** Productos ordenados por peso ascendente (requisito de la búsqueda binaria). */
  productsByWeight: Product[];
  shipments: Shipment[];
}

const modes: { value: LookupMode; label: string; placeholder: string; fn: string }[] = [
  { value: "shipment", label: "Envío por ID", placeholder: "SH-2024-8821", fn: "findShipmentById" },
  { value: "sku", label: "Producto por SKU", placeholder: "laptop-dell-15", fn: "findProductBySKU" },
  { value: "weight", label: "Producto por peso (kg)", placeholder: "2.3", fn: "binarySearchProductByWeight" },
];

export function RecordLookup({ products, productsByWeight, shipments }: RecordLookupProps) {
  const [mode, setMode] = useState<LookupMode>("shipment");
  const [query, setQuery] = useState("SH-2024-8821");

  const active = modes.find((item) => item.value === mode) ?? modes[0];
  const trimmed = query.trim();

  let result: React.ReactNode = null;
  if (trimmed !== "") {
    if (mode === "shipment") {
      const shipment = findShipmentById(shipments, trimmed);
      result = shipment ? (
        <p>
          <strong>{shipment.id}</strong> · {warehouseLabels[shipment.origin]} →{" "}
          {shipment.destination.city} ({countryLabels[shipment.destination.country]}) ·{" "}
          {priorityLabels[shipment.priority]} ·{" "}
          <Badge tone="info">{shipmentStatusLabels[shipment.status]}</Badge> · transportista:{" "}
          {shipment.carrier ?? "sin asignar"}
        </p>
      ) : null;
    } else if (mode === "sku") {
      const product = findProductBySKU(products, trimmed);
      result = product ? (
        <p>
          <strong>{product.sku}</strong> · {product.name} · {product.stockQuantity} uds. en{" "}
          {warehouseLabels[product.warehouse]}
        </p>
      ) : null;
    } else {
      const weight = Number(trimmed);
      const index = Number.isFinite(weight)
        ? binarySearchProductByWeight(productsByWeight, weight)
        : -1;
      const product = index >= 0 ? productsByWeight[index] : null;
      result = product ? (
        <p>
          Índice <strong>{index}</strong> en la lista ordenada · {product.name} ({product.weightKg} kg)
        </p>
      ) : null;
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Tipo de búsqueda">
        {modes.map((item) => (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={mode === item.value}
            onClick={() => {
              setMode(item.value);
              setQuery(item.placeholder);
            }}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${mode === item.value ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
          >
            {item.label}
          </button>
        ))}
      </div>
      <label className="block text-sm font-medium text-slate-700">
        Buscar con <code className="font-mono text-xs">{active.fn}</code>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={active.placeholder}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-cyan-600 focus:outline-none focus:ring-2 focus:ring-cyan-600/20"
        />
      </label>
      <div className="min-h-12 rounded-md bg-slate-50 p-3 text-sm text-slate-700" aria-live="polite">
        {trimmed === "" ? "Escribe un valor para buscar." : result ?? "Sin resultados (la función devuelve null / -1)."}
      </div>
    </div>
  );
}
