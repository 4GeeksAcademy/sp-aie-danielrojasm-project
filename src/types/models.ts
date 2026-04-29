//Product
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

//Shipment
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

  //Carrier
  interface Carrier {
    id: string; // ID del transportista (ej: "CAR-UPS")
    name: string; // Nombre del transportista (ej: "UPS")
    operatesIn: Country[]; // Países donde opera
    baseRateUSD: number; // Costo base de entrega (USD)
    ratePerKgUSD: number; // Costo adicional por kg (USD)
    ratePerKmUSD: number; // Costo adicional por km (USD)
    avgDeliveryDays: number; // Tiempo promedio de entrega en días
    onTimeRate: number; // Tasa de entrega a tiempo (0-100)
    maxWeightKg: number; // Peso máximo de paquete que aceptan
    handlesFragile: boolean; // Puede manejar ítems frágiles
    acceptsPriority: ShipmentPriority[]; // Prioridades que soportan
}
//InventoryMovement
interface InventoryMovement {
  id: string; // ID del movimiento
  sku: string; // SKU del producto
  warehouse: WarehouseLocation; // Ubicación del almacén
  type: MovementType; // Entrada o salida
  quantity: number; // Número de unidades movidas
  reason: string; // Razón del movimiento
  timestamp: Date; // Cuándo sucedió
}

type MovementType = "Inbound" | "Outbound" | "Transfer" | "Adjustment";