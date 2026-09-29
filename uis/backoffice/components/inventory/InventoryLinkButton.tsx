import Link from "next/link";
import type { ReactNode } from "react";

interface InventoryLinkButtonProps {
  href: string;
  children: ReactNode;
  variant?: "primary" | "secondary";
  /** Texto completo para lectores de pantalla cuando el visible es corto. */
  ariaLabel?: string;
  size?: "md" | "sm";
}

const variantClasses = {
  primary: "bg-slate-950 text-white hover:bg-slate-800",
  secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-100",
};

const sizeClasses = {
  md: "h-10 px-4 text-sm",
  sm: "h-8 px-2.5 text-xs",
};

export function InventoryLinkButton({
  href,
  children,
  variant = "secondary",
  ariaLabel,
  size = "md",
}: InventoryLinkButtonProps) {
  return (
    <Link
      href={href}
      aria-label={ariaLabel}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md font-semibold ${variantClasses[variant]} ${sizeClasses[size]}`}
    >
      {children}
    </Link>
  );
}
