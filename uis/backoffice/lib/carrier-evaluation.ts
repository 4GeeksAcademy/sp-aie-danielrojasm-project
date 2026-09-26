import {
  calculateShippingCost,
  scoreCarrierForShipment,
  selectBestCarrier,
} from "@trackflow/logic/utils/transformations";
import type {
  Carrier,
  Product,
  Shipment,
} from "@trackflow/logic/types/models";

/** Mismo umbral que aplica selectBestCarrier (src/utils/transformations.ts). */
export const SUITABILITY_THRESHOLD = 50;

export interface CarrierEvaluation {
  carrier: Carrier;
  score: number;
  cost: number;
  suitable: boolean;
  isBest: boolean;
}

/**
 * Restricciones duras que el scoring del Hito 2 solo pondera (no excluye).
 * Se usan únicamente para avisar en la UI; la recomendación no se altera.
 * Ver "Problemas conocidos" en memory-bank/progress.md.
 */
export function findHardConstraintIssues(
  carrier: Carrier,
  shipment: Shipment,
  product: Product,
): string[] {
  const issues: string[] = [];
  if (!carrier.operatesIn.includes(shipment.destination.country)) {
    issues.push(`${carrier.name} no opera en el país de destino.`);
  }
  if (product.weightKg * shipment.quantity > carrier.maxWeightKg) {
    issues.push(`El envío supera el peso máximo de ${carrier.name}.`);
  }
  if (!carrier.acceptsPriority.includes(shipment.priority)) {
    issues.push(`${carrier.name} no acepta esta prioridad.`);
  }
  if (product.isFragile && !carrier.handlesFragile) {
    issues.push(`${carrier.name} no maneja productos frágiles.`);
  }
  return issues;
}

/**
 * Adapta la salida del Hito 2 a filas de tabla: puntúa y cotiza cada
 * transportista y marca el elegido por selectBestCarrier. No recalcula nada.
 */
export function evaluateCarriers(
  carriers: Carrier[],
  shipment: Shipment,
  product: Product,
): { rows: CarrierEvaluation[]; best: ReturnType<typeof selectBestCarrier> } {
  const best = selectBestCarrier(carriers, shipment, product);

  const rows = carriers
    .map((carrier) => {
      const score = scoreCarrierForShipment(carrier, shipment, product);
      return {
        carrier,
        score,
        cost: calculateShippingCost(shipment, product, carrier),
        suitable: score >= SUITABILITY_THRESHOLD,
        isBest: best?.carrier.id === carrier.id,
      };
    })
    .sort((a, b) => b.score - a.score);

  return { rows, best };
}
