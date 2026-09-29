import type { Metadata } from "next";
import { InventoryOrderHistory } from "@/components/inventory/InventoryOrderHistory";

export const metadata: Metadata = { title: "Historial de movimientos" };

export default function InventoryOrdersPage() {
  return <InventoryOrderHistory />;
}
