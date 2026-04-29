interface Shipment {
  id: string; // ID único de envío (ej: "SH-2024-8821")
  sku: string; // SKU del producto siendo enviado
  quantity: number; // Número de unidades
  origin: WarehouseLocation; // Almacén de origen
  destination: Destination; // Destino de entrega
  priority: ShipmentPriority; // Nivel de urgencia
  declaredValueUSD: number; // Valor declarado para seguro
  carrier: string | null; // Transportista asignado (null si no asignado)
  status: ShipmentStatus; // Estado actual
  createdAt: Date; // Fecha de creación del pedido
}

interface Destination {
  city: string;
  country: Country;
  postalCode: string;
  distanceKm: number; // Distancia desde el almacén de origen
}

type Country = "United States" | "Spain";
type ShipmentPriority = "Standard" | "Express" | "Same-day";
type ShipmentStatus =
  | "Pending"
  | "Assigned"
  | "In transit"
  | "Delivered"
  | "Failed";
type WarehouseLocation = "Los Angeles" | "Zaragoza";
type ProductStatus = "Active" | "Low stock" | "Out of stock" | "Discontinued";