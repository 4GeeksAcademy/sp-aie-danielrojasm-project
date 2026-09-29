import type { Metadata } from "next";
import { InventoryStockTable } from "@/components/inventory/InventoryStockTable";

export const metadata: Metadata = { title: "Stock por SKU" };

export default function InventoryProductsPage() {
  return <InventoryStockTable />;
}
