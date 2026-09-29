import type { Metadata } from "next";
import { StockExitForm } from "@/components/inventory/StockExitForm";
import { parseSkuParam } from "@/lib/inventory";

export const metadata: Metadata = { title: "Registrar salida de stock" };

export default async function StockExitPage({
  searchParams,
}: {
  searchParams: Promise<{ sku?: string | string[] }>;
}) {
  const { sku } = await searchParams;
  return <StockExitForm initialSkuId={parseSkuParam(sku)} />;
}
