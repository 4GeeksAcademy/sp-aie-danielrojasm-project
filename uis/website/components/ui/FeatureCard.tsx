import type { FeatureItem } from "@/types/site";

interface FeatureCardProps {
  item: FeatureItem;
  variant?: "card" | "compact";
}

/** Tarjeta reutilizable para servicios (card) y beneficios (compact). */
export function FeatureCard({ item, variant = "card" }: FeatureCardProps) {
  if (variant === "compact") {
    return (
      <div className="rounded-xl border border-slate-700 bg-slate-950 p-4">
        <h3 className="font-semibold text-cyan-100">{item.title}</h3>
        <p className="text-slate-300">{item.description}</p>
      </div>
    );
  }

  return (
    <article className="rounded-2xl border border-slate-700 bg-slate-900 p-6 transition hover:border-cyan-300/50">
      <h3 className="text-xl font-bold text-cyan-200">{item.title}</h3>
      <p className="mt-3 text-slate-300">{item.description}</p>
    </article>
  );
}
