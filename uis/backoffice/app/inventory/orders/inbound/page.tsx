import type { Metadata } from "next";
import { StockEntryForm } from "@/components/inventory/StockEntryForm";
import { parseSkuParam } from "@/lib/inventory";

export const metadata: Metadata = { title: "Registrar entrada de stock" };

export default async function StockEntryPage({
  searchParams,
}: {
  searchParams: Promise<{ sku?: string | string[] }>;
}) {
  const { sku } = await searchParams;
  return <StockEntryForm initialSkuId={parseSkuParam(sku)} />;
}
