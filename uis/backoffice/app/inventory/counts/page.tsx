import type { Metadata } from "next";
import { InventoryCountForm } from "@/components/inventory/InventoryCountForm";
import { parseSkuParam } from "@/lib/inventory";

export const metadata: Metadata = { title: "Conteo físico" };

export default async function InventoryCountPage({
  searchParams,
}: {
  searchParams: Promise<{ sku?: string | string[] }>;
}) {
  const { sku } = await searchParams;
  return <InventoryCountForm initialSkuId={parseSkuParam(sku)} />;
}
