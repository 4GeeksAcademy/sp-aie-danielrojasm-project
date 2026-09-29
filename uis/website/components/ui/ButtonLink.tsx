import Link from "next/link";
import type { ReactNode } from "react";

type ButtonVariant = "primary" | "outline" | "light" | "ghost-light";

const variantClasses: Record<ButtonVariant, string> = {
  primary: "bg-cyan-300 text-slate-950 font-bold hover:bg-cyan-200",
  outline:
    "border border-slate-500 text-white font-semibold hover:border-cyan-200 hover:text-cyan-100",
  light: "bg-white text-slate-900 font-bold hover:bg-slate-100",
  "ghost-light":
    "border border-white/50 text-white font-semibold hover:bg-white/10",
};

interface ButtonLinkProps {
  href: string;
  children: ReactNode;
  variant?: ButtonVariant;
  ariaLabel?: string;
}

export function ButtonLink({
  href,
  children,
  variant = "primary",
  ariaLabel,
}: ButtonLinkProps) {
  const className = `inline-flex items-center justify-center rounded-lg px-6 py-3 text-base transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 ${variantClasses[variant]}`;
  const isExternal = href.startsWith("mailto:") || href.startsWith("http");

  if (isExternal) {
    return (
      <a href={href} className={className} aria-label={ariaLabel}>
        {children}
      </a>
    );
  }

  return (
    <Link href={href} className={className} aria-label={ariaLabel}>
      {children}
    </Link>
  );
}
