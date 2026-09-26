import {
  CARRIER_SUITABILITY_THRESHOLD,
  calculateShippingCost,
  checkCarrierConstraints,
  scoreCarrierForShipment,
  selectBestCarrier,
  type CarrierConstraintChecks,
} from "@trackflow/logic/utils/transformations";
import type {
  Carrier,
  Product,
  Shipment,
} from "@trackflow/logic/types/models";

export interface CarrierEvaluation {
  carrier: Carrier;
  score: number;
  cost: number;
  suitable: boolean;
  isBest: boolean;
}

const constraintMessages: Record<
  keyof CarrierConstraintChecks,
  (carrierName: string) => string
> = {
  operatesInDestination: (name) => `${name} no opera en el país de destino.`,
  supportsWeight: (name) => `El envío supera el peso máximo de ${name}.`,
  supportsPriority: (name) => `${name} no acepta esta prioridad.`,
  supportsFragility: (name) => `${name} no maneja productos frágiles.`,
};

/**
 * Traduce a mensajes los criterios que el scoring del Hito 2 solo pondera
 * (no excluye). Los criterios vienen de checkCarrierConstraints (src/); aquí
 * solo se redactan. Ver "Problemas conocidos" en memory-bank/progress.md.
 */
export function findHardConstraintIssues(
  carrier: Carrier,
  shipment: Shipment,
  product: Product,
): string[] {
  const checks = checkCarrierConstraints(carrier, shipment, product);
  return (Object.keys(checks) as (keyof CarrierConstraintChecks)[])
    .filter((key) => !checks[key])
    .map((key) => constraintMessages[key](carrier.name));
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
        suitable: score >= CARRIER_SUITABILITY_THRESHOLD,
        isBest: best?.carrier.id === carrier.id,
      };
    })
    .sort((a, b) => b.score - a.score);

  return { rows, best };
}
