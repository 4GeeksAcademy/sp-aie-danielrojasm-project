"use client";

import { useMemo, useState } from "react";
import { findProductBySKU } from "@trackflow/logic/utils/search";
import { validateShipment } from "@trackflow/logic/utils/validations";
import type {
  Carrier,
  Country,
  Product,
  Shipment,
  ShipmentPriority,
} from "@trackflow/logic/types/models";
import { CarrierEvaluationTable } from "@/components/dashboard/CarrierEvaluationTable";
import {
  evaluateCarriers,
  findHardConstraintIssues,
} from "@/lib/carrier-evaluation";
import { countryLabels, formatUSD, priorityLabels } from "@/lib/labels";

interface CarrierSimulatorProps {
  products: Product[];
  carriers: Carrier[];
  /** Envío de partida (SH-2024-8821 de CONTEXT2.md). */
  initialShipment: Shipment;
}

const fieldClass =
  "mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-cyan-600 focus:outline-none focus:ring-2 focus:ring-cyan-600/20";

export function CarrierSimulator({
  products,
  carriers,
  initialShipment,
}: CarrierSimulatorProps) {
  const [sku, setSku] = useState(initialShipment.sku);
  const [country, setCountry] = useState<Country>(initialShipment.destination.country);
  const [priority, setPriority] = useState<ShipmentPriority>(initialShipment.priority);
  const [quantity, setQuantity] = useState(initialShipment.quantity);
  const [distanceKm, setDistanceKm] = useState(initialShipment.destination.distanceKm);

  const product = findProductBySKU(products, sku);

  const shipment: Shipment = useMemo(
    () => ({
      ...initialShipment,
      sku,
      quantity,
      priority,
      declaredValueUSD: product ? product.unitCostUSD * quantity : 0,
      destination: { ...initialShipment.destination, country, distanceKm },
    }),
    [initialShipment, sku, quantity, priority, country, distanceKm, product],
  );

  const validation = validateShipment(shipment);
  const evaluation =
    product && validation.valid ? evaluateCarriers(carriers, shipment, product) : null;
  const bestIssues =
    product && evaluation?.best
      ? findHardConstraintIssues(evaluation.best.carrier, shipment, product)
      : [];

  return (
    <div className="grid gap-6 xl:grid-cols-[280px_1fr]">
      <form className="space-y-3" onSubmit={(event) => event.preventDefault()}>
        <label className="block text-sm font-medium text-slate-700">
          Producto
          <select value={sku} onChange={(e) => setSku(e.target.value)} className={fieldClass}>
            {products
              .filter((item) => item.sku.trim() !== "")
              .map((item) => (
                <option key={item.sku} value={item.sku}>
                  {item.name}
                </option>
              ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-700">
          País de destino
          <select value={country} onChange={(e) => setCountry(e.target.value as Country)} className={fieldClass}>
            {(Object.keys(countryLabels) as Country[]).map((value) => (
              <option key={value} value={value}>
                {countryLabels[value]}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-700">
          Prioridad
          <select value={priority} onChange={(e) => setPriority(e.target.value as ShipmentPriority)} className={fieldClass}>
            {(Object.keys(priorityLabels) as ShipmentPriority[]).map((value) => (
              <option key={value} value={value}>
                {priorityLabels[value]}
              </option>
            ))}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm font-medium text-slate-700">
            Unidades
            <input type="number" min={0} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} className={fieldClass} />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Distancia (km)
            <input type="number" value={distanceKm} onChange={(e) => setDistanceKm(Number(e.target.value))} className={fieldClass} />
          </label>
        </div>
      </form>

      <div aria-live="polite">
        {!validation.valid ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            <p className="font-semibold">El envío no es válido (validateShipment):</p>
            <ul className="mt-2 list-inside list-disc">
              {validation.errors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          </div>
        ) : evaluation ? (
          <>
            <div
              className={`mb-4 rounded-lg border p-4 text-sm ${evaluation.best ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}
            >
              {evaluation.best ? (
                <p>
                  <span className="font-semibold">Recomendación:</span>{" "}
                  {evaluation.best.carrier.name} · puntuación{" "}
                  {evaluation.best.score.toFixed(2)} · coste{" "}
                  {formatUSD(evaluation.best.cost)} · {evaluation.best.carrier.avgDeliveryDays}{" "}
                  día(s) de media
                </p>
              ) : (
                <p>
                  <span className="font-semibold">Sin transportista apto:</span>{" "}
                  ninguno alcanza 50 puntos para este envío.
                </p>
              )}
            </div>
            {bestIssues.length > 0 ? (
              <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900" role="alert">
                <p className="font-semibold">
                  Revisión manual: la recomendación incumple una restricción operativa
                </p>
                <ul className="mt-1 list-inside list-disc">
                  {bestIssues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
                <p className="mt-2 text-xs">
                  El scoring del Hito 2 pondera estos criterios en lugar de excluir; con 50
                  puntos de umbral puede ganar el más barato aunque no pueda entregar.
                </p>
              </div>
            ) : null}
            <CarrierEvaluationTable rows={evaluation.rows} />
          </>
        ) : null}
      </div>
    </div>
  );
}
