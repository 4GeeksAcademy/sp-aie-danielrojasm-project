"use client";

import { FormEvent, useMemo, useState } from "react";
import {
  STAGE_OPTIONS,
  STATUS_OPTIONS,
  TRACKFLOW_POSITION,
  getStageLabel,
  getStatusLabel,
} from "@/lib/domain";
import {
  Candidate,
  CandidateFormValues,
  CandidateStage,
  CandidateStatus,
} from "@/types/candidate";
import { getUserMessage } from "@/services/recordsApi";

interface CandidateFormProps {
  mode: "create" | "edit";
  initialCandidate?: Candidate;
  onSubmit: (values: CandidateFormValues) => Promise<Candidate>;
  onSuccess?: (candidate: Candidate) => void;
  title: string;
  submitLabel: string;
}

export function toFormValues(candidate?: Candidate): CandidateFormValues {
  return {
    name: candidate?.name || "",
    email: candidate?.email || "",
    phone: candidate?.phone || "",
    position: candidate?.position || TRACKFLOW_POSITION,
    linkedinUrl: candidate?.linkedinUrl || "",
    cvUrl: candidate?.cvUrl || "",
    yearsExperience:
      candidate?.yearsExperience !== undefined
        ? String(candidate.yearsExperience)
        : "",
    status: candidate?.status || "received",
    stage: candidate?.stage || "pending",
    appliedAt: candidate?.appliedAt
      ? candidate.appliedAt.slice(0, 10)
      : new Date().toISOString().slice(0, 10),
  };
}

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function isValidUrl(url: string): boolean {
  if (!url) {
    return true;
  }

  try {
    const parsedUrl = new URL(url);
    return parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:";
  } catch {
    return false;
  }
}

function validate(values: CandidateFormValues): string | null {
  if (!values.name.trim()) return "El nombre es obligatorio.";
  if (!values.email.trim()) return "El email es obligatorio.";
  if (!isValidEmail(values.email)) return "El email no tiene un formato valido.";
  if (!values.phone.trim()) return "El teléfono es obligatorio.";
  if (!values.position.trim()) return "El puesto es obligatorio.";
  if (!values.appliedAt.trim()) return "La fecha de aplicación es obligatoria.";

  const years = Number(values.yearsExperience);
  if (values.yearsExperience.trim() === "" || Number.isNaN(years) || years < 0) {
    return "Los años de experiencia deben ser un número mayor o igual a 0.";
  }

  if (!isValidUrl(values.linkedinUrl)) {
    return "El enlace de LinkedIn debe ser una URL valida (http o https).";
  }

  if (!isValidUrl(values.cvUrl)) {
    return "El enlace del CV debe ser una URL valida (http o https).";
  }

  return null;
}

export default function CandidateForm({
  mode,
  initialCandidate,
  onSubmit,
  onSuccess,
  title,
  submitLabel,
}: CandidateFormProps) {
  const [values, setValues] = useState<CandidateFormValues>(() =>
    toFormValues(initialCandidate),
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const actionDescription = useMemo(
    () => (mode === "create" ? "registrada" : "actualizada"),
    [mode],
  );

  const handleChange = (
    field: keyof CandidateFormValues,
    value: string | CandidateStatus | CandidateStage,
  ) => {
    setValues((previousValues) => ({
      ...previousValues,
      [field]: String(value),
    }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);

    const validationError = validate(values);
    if (validationError) {
      setErrorMessage(validationError);
      return;
    }

    setIsSubmitting(true);

    try {
      const updatedCandidate = await onSubmit(values);
      setSuccessMessage(`Candidatura ${actionDescription} correctamente.`);
      onSuccess?.(updatedCandidate);

      if (mode === "create") {
        setValues(toFormValues());
      }
    } catch (error) {
      setErrorMessage(
        getUserMessage(error, "No se pudo enviar el formulario. Inténtalo de nuevo."),
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="rounded-2xl border border-slate-700 bg-slate-900/80 p-4 shadow-lg shadow-black/20">
      <h2 className="mb-4 text-lg font-bold text-cyan-100">{title}</h2>

      <form className="grid gap-3" onSubmit={handleSubmit}>
        <label className="grid gap-1 text-sm font-semibold text-slate-200">
          Nombre completo
          <input
            className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
            value={values.name}
            onChange={(event) => handleChange("name", event.target.value)}
            required
          />
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-200">
          Email
          <input
            className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
            type="email"
            value={values.email}
            onChange={(event) => handleChange("email", event.target.value)}
            required
          />
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-200">
          Teléfono
          <input
            className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
            value={values.phone}
            onChange={(event) => handleChange("phone", event.target.value)}
            required
          />
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-200">
          Puesto
          <input
            className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
            value={values.position}
            onChange={(event) => handleChange("position", event.target.value)}
            required
          />
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-200">
          LinkedIn
          <input
            className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
            type="url"
            placeholder="https://linkedin.com/in/..."
            value={values.linkedinUrl}
            onChange={(event) => handleChange("linkedinUrl", event.target.value)}
          />
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-200">
          Enlace al CV
          <input
            className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
            type="url"
            placeholder="https://..."
            value={values.cvUrl}
            onChange={(event) => handleChange("cvUrl", event.target.value)}
          />
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-200">
          Años de experiencia
          <input
            className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
            type="number"
            min={0}
            value={values.yearsExperience}
            onChange={(event) =>
              handleChange("yearsExperience", event.target.value)
            }
            required
          />
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-200">
          Estado
          <select
            className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
            value={values.status}
            onChange={(event) =>
              handleChange("status", event.target.value as CandidateStatus)
            }
            required
          >
            {STATUS_OPTIONS.map((statusValue) => (
              <option key={statusValue} value={statusValue}>
                {getStatusLabel(statusValue)}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-200">
          Etapa
          <select
            className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
            value={values.stage}
            onChange={(event) =>
              handleChange("stage", event.target.value as CandidateStage)
            }
            required
          >
            {STAGE_OPTIONS.map((stageValue) => (
              <option key={stageValue} value={stageValue}>
                {getStageLabel(stageValue)}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1 text-sm font-semibold text-slate-200">
          Fecha de aplicación
          <input
            className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
            type="date"
            value={values.appliedAt}
            onChange={(event) => handleChange("appliedAt", event.target.value)}
            required
          />
        </label>

        <button
          type="submit"
          className="mt-2 rounded-lg bg-cyan-300 px-4 py-2 text-sm font-bold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-70"
          disabled={isSubmitting}
        >
          {isSubmitting ? "Guardando..." : submitLabel}
        </button>
      </form>

      {errorMessage && (
        <p className="mt-3 rounded-lg border border-rose-300/40 bg-rose-400/10 px-3 py-2 text-sm text-rose-200">
          {errorMessage}
        </p>
      )}

      {successMessage && (
        <p className="mt-3 rounded-lg border border-emerald-300/40 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-200">
          {successMessage}
        </p>
      )}
    </section>
  );
}
