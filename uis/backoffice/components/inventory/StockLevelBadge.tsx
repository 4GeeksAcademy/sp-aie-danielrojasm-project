import { formatUnits, getStockLevel, stockLevelLabels, type StockLevel } from "@/lib/inventory";

interface StockLevelBadgeProps {
  stock: number;
}

const levelClasses: Record<StockLevel, string> = {
  out: "bg-rose-100 text-rose-800 ring-rose-200",
  low: "bg-amber-100 text-amber-900 ring-amber-200",
  healthy: "bg-emerald-100 text-emerald-800 ring-emerald-200",
};

const dotClasses: Record<StockLevel, string> = {
  out: "bg-rose-500",
  low: "bg-amber-500",
  healthy: "bg-emerald-500",
};

/** Cifra de stock con su nivel: el color nunca es la única pista (lleva texto). */
export function StockLevelBadge({ stock }: StockLevelBadgeProps) {
  const level = getStockLevel(stock);
  return (
    <span className="inline-flex items-center gap-3">
      <span className="min-w-12 text-right text-base font-bold tabular-nums text-slate-950">
        {formatUnits(stock)}
      </span>
      <span
        className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${levelClasses[level]}`}
      >
        <span aria-hidden="true" className={`h-2 w-2 rounded-full ${dotClasses[level]}`} />
        {stockLevelLabels[level]}
      </span>
    </span>
  );
}
