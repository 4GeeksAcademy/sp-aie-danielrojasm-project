import type { ReactNode } from "react";

export const inputBaseClass =
  "w-full rounded-lg border bg-slate-950 px-4 py-3 text-slate-100 outline-none transition focus:ring-2";

export function inputStateClass(hasError: boolean): string {
  return hasError
    ? "border-rose-400 focus:border-rose-400 focus:ring-rose-400/20"
    : "border-slate-600 focus:border-cyan-300 focus:ring-cyan-300/30";
}

interface FieldErrorProps {
  id: string;
  message?: string;
}

export function FieldError({ id, message }: FieldErrorProps) {
  if (!message) return null;
  return (
    <p id={id} className="mt-2 text-sm font-medium text-rose-300" role="alert">
      {message}
    </p>
  );
}

interface FormFieldProps {
  id: string;
  label: string;
  required?: boolean;
  error?: string;
  className?: string;
  children: ReactNode;
}

/** Envoltorio accesible: etiqueta + control + mensaje de error asociado. */
export function FormField({
  id,
  label,
  required = false,
  error,
  className,
  children,
}: FormFieldProps) {
  return (
    <div className={className}>
      <label
        htmlFor={id}
        className="mb-2 block text-sm font-semibold text-slate-100"
      >
        {label}
        {required ? " *" : ""}
      </label>
      {children}
      <FieldError id={`${id}-error`} message={error} />
    </div>
  );
}

interface FieldsetProps {
  legend: string;
  children: ReactNode;
}

export function Fieldset({ legend, children }: FieldsetProps) {
  return (
    <fieldset className="space-y-5">
      <legend className="mb-3 text-lg font-bold text-cyan-100">{legend}</legend>
      {children}
    </fieldset>
  );
}
