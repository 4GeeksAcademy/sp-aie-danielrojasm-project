import type { ReactNode } from "react";

interface FormFieldProps {
  id: string;
  label: string;
  /** Recibe el `aria-describedby` que debe llevar el control. */
  children: (describedBy: string | undefined) => ReactNode;
  hint?: string;
  error?: string;
}

export function fieldHintId(id: string): string {
  return `${id}-hint`;
}

export function fieldErrorId(id: string): string {
  return `${id}-error`;
}

export function FormField({ id, label, children, hint, error }: FormFieldProps) {
  const describedBy =
    [hint ? fieldHintId(id) : null, error ? fieldErrorId(id) : null].filter(Boolean).join(" ") ||
    undefined;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-800">
        {label}
      </label>
      <div className="mt-1.5">{children(describedBy)}</div>
      {hint ? (
        <p id={fieldHintId(id)} className="mt-1.5 text-xs text-slate-500">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={fieldErrorId(id)} role="alert" className="mt-1.5 text-sm text-rose-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Clases comunes de `input` y `select`, con borde rojo si hay error. */
export function controlClasses(hasError: boolean): string {
  return `block h-11 w-full rounded-md border bg-white px-3 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:bg-slate-100 ${
    hasError ? "border-rose-400" : "border-slate-300"
  }`;
}
