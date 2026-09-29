/**
 * Etiquetas en español para los valores de dominio del Hito 2.
 * Los valores crudos (p. ej. "In transit", "Same-day") no se muestran en la UI.
 */
import type {
  Country,
  ProductCategory,
  ProductStatus,
  ShipmentPriority,
  ShipmentStatus,
  WarehouseLocation,
} from "@trackflow/logic/types/models";

export const shipmentStatusLabels: Record<ShipmentStatus, string> = {
  Pending: "Pendiente",
  Assigned: "Asignado",
  "In transit": "En tránsito",
  Delivered: "Entregado",
  Failed: "Fallido",
};

export const priorityLabels: Record<ShipmentPriority, string> = {
  Standard: "Estándar",
  Express: "Exprés",
  "Same-day": "Mismo día",
};

export const categoryLabels: Record<ProductCategory, string> = {
  Fashion: "Moda",
  Electronics: "Electrónica",
  Cosmetics: "Cosmética",
  Home: "Hogar",
  Other: "Otros",
};

export const productStatusLabels: Record<ProductStatus, string> = {
  Active: "Activo",
  "Low stock": "Stock bajo",
  "Out of stock": "Sin stock",
  Discontinued: "Descatalogado",
};

export const countryLabels: Record<Country, string> = {
  "United States": "Estados Unidos",
  Spain: "España",
};

export const warehouseLabels: Record<WarehouseLocation, string> = {
  "Los Angeles": "Los Ángeles",
  Zaragoza: "Zaragoza",
};

const usdFormatter = new Intl.NumberFormat("es-ES", {
  style: "currency",
  currency: "USD",
});

export function formatUSD(value: number): string {
  return usdFormatter.format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2 }).format(
    value,
  );
}
