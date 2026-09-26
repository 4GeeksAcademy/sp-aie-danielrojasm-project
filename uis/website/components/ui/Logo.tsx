import Link from "next/link";

interface LogoProps {
  subtitle: string;
}

export function Logo({ subtitle }: LogoProps) {
  return (
    <Link
      href="/"
      className="inline-flex items-center gap-3"
      aria-label="Ir al inicio de TrackFlow"
    >
      <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-300 font-black text-slate-950">
        TF
      </span>
      <span>
        <span className="block text-lg font-bold leading-none">TrackFlow</span>
        <span className="block text-xs uppercase tracking-[0.2em] text-cyan-200">
          {subtitle}
        </span>
      </span>
    </Link>
  );
}
