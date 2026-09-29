"use client";

import { useState, type FormEvent } from "react";
import { UserPlus } from "lucide-react";
import { useAuth } from "@/components/auth/AuthProvider";
import { ApiError } from "@/lib/api-client";

type RegistrationField =
  | "email"
  | "password"
  | "confirmPassword"
  | "name"
  | "phone"
  | "address";

type FieldErrors = Partial<Record<RegistrationField, string>>;

const registrationFields = new Set<RegistrationField>([
  "email",
  "password",
  "name",
  "phone",
  "address",
]);

function validateRegistration(formData: FormData): FieldErrors {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const confirmPassword = String(formData.get("confirmPassword") ?? "");
  const errors: FieldErrors = {};

  if (!email) errors.email = "Introduce tu email.";
  else if (!/^\S+@\S+\.\S+$/.test(email)) errors.email = "Introduce un email válido.";
  if (password.length < 8) errors.password = "Usa al menos 8 caracteres.";
  else if (password.length > 72) errors.password = "Usa un máximo de 72 caracteres.";
  if (confirmPassword !== password) errors.confirmPassword = "Las contraseñas no coinciden.";
  return errors;
}

function apiFieldErrors(error: ApiError): FieldErrors {
  if (error.status === 409) return { email: error.message };
  if (!Array.isArray(error.body?.detail)) return {};

  return error.body.detail.reduce<FieldErrors>((errors, detail) => {
    const field = detail.loc?.at(-1);
    if (
      typeof field === "string" &&
      registrationFields.has(field as RegistrationField) &&
      detail.msg
    ) {
      errors[field as RegistrationField] = detail.msg;
    }
    return errors;
  }, {});
}

interface FieldProps {
  id: RegistrationField;
  label: string;
  type?: "text" | "email" | "password" | "tel";
  autoComplete: string;
  required?: boolean;
  error?: string;
}

function RegistrationFieldInput({
  id,
  label,
  type = "text",
  autoComplete,
  required,
  error,
}: FieldProps) {
  return (
    <div>
      <label htmlFor={`register-${id}`} className="text-sm font-medium text-slate-800">
        {label}{required ? " *" : ""}
      </label>
      <input
        id={`register-${id}`}
        name={id}
        type={type}
        autoComplete={autoComplete}
        required={required}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `register-${id}-error` : undefined}
        className="mt-2 block w-full rounded-md border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-cyan-700 focus:ring-2 focus:ring-cyan-100 aria-invalid:border-rose-500"
      />
      {error ? (
        <p id={`register-${id}-error`} className="mt-1.5 text-xs text-rose-700" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function RegisterForm() {
  const { register } = useAuth();
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [requestError, setRequestError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const validationErrors = validateRegistration(formData);
    setFieldErrors(validationErrors);
    setRequestError("");
    if (Object.keys(validationErrors).length > 0) return;

    setIsSubmitting(true);
    try {
      await register({
        email: String(formData.get("email") ?? "").trim(),
        password: String(formData.get("password") ?? ""),
        name: String(formData.get("name") ?? "").trim() || undefined,
        phone: String(formData.get("phone") ?? "").trim() || undefined,
        address: String(formData.get("address") ?? "").trim() || undefined,
      });
    } catch (error) {
      const serverFieldErrors = error instanceof ApiError ? apiFieldErrors(error) : {};
      if (Object.keys(serverFieldErrors).length > 0) {
        setFieldErrors(serverFieldErrors);
      } else {
        setRequestError(error instanceof Error ? error.message : "No se pudo crear la cuenta.");
      }
      setIsSubmitting(false);
    }
  }

  return (
    <form className="space-y-5" onSubmit={handleSubmit} noValidate>
      {requestError ? (
        <p className="border-l-4 border-rose-500 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">
          {requestError}
        </p>
      ) : null}

      <div className="grid gap-5 sm:grid-cols-2">
        <RegistrationFieldInput id="email" label="Email" type="email" autoComplete="email" required error={fieldErrors.email} />
        <RegistrationFieldInput id="name" label="Nombre visible" autoComplete="name" error={fieldErrors.name} />
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <RegistrationFieldInput id="password" label="Contraseña" type="password" autoComplete="new-password" required error={fieldErrors.password} />
        <RegistrationFieldInput id="confirmPassword" label="Confirmar contraseña" type="password" autoComplete="new-password" required error={fieldErrors.confirmPassword} />
      </div>
      <RegistrationFieldInput id="phone" label="Teléfono" type="tel" autoComplete="tel" error={fieldErrors.phone} />
      <RegistrationFieldInput id="address" label="Dirección" autoComplete="street-address" error={fieldErrors.address} />

      <button
        type="submit"
        disabled={isSubmitting}
        className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <UserPlus aria-hidden="true" className="h-4 w-4" />
        {isSubmitting ? "Creando cuenta..." : "Crear cuenta"}
      </button>
    </form>
  );
}