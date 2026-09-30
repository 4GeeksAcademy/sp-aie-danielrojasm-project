import type { ReactNode } from "react";

interface PanelProps {
  id?: string;
  title: string;
  description?: string;
  /** Función del Hito 2 que produce el contenido, para trazabilidad. */
  source?: string;
  children: ReactNode;
}

export function Panel({ id, title, description, source, children }: PanelProps) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      className="min-w-0 scroll-mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={headingId} className="text-lg font-semibold text-slate-900">
            {title}
          </h2>
          {description ? (
            <p className="mt-1 text-sm text-slate-500">{description}</p>
          ) : null}
        </div>
        {source ? (
          <code className="rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-600">
            {source}
          </code>
        ) : null}
      </div>
      {children}
    </section>
  );
}

interface KpiCardProps {
  label: string;
  value: string;
  hint: string;
  tone?: "default" | "warning" | "danger";
}

const toneClasses: Record<NonNullable<KpiCardProps["tone"]>, string> = {
  default: "text-slate-900",
  warning: "text-amber-700",
  danger: "text-rose-700",
};

export function KpiCard({ label, value, hint, tone = "default" }: KpiCardProps) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className={`mt-2 text-3xl font-bold tabular-nums ${toneClasses[tone]}`}>
        {value}
      </p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  );
}

type BadgeTone = "neutral" | "success" | "warning" | "danger" | "info";

const badgeClasses: Record<BadgeTone, string> = {
  neutral: "bg-slate-100 text-slate-700",
  success: "bg-emerald-100 text-emerald-800",
  warning: "bg-amber-100 text-amber-800",
  danger: "bg-rose-100 text-rose-800",
  info: "bg-cyan-100 text-cyan-800",
};

export function Badge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${badgeClasses[tone]}`}
    >
      {children}
    </span>
  );
}
