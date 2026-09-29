"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  branchLabels,
  branches,
  createIncident,
  incidentCategories,
  incidentCategoryHints,
  incidentCategoryLabels,
  incidentOriginHints,
  incidentOriginLabels,
  incidentOrigins,
  incidentStatusLabels,
  TITLE_MAX_LENGTH,
  toFriendlyError,
  validateIncidentForm,
  type Incident,
  type IncidentFormErrors,
  type IncidentFormField,
  type IncidentFormValues,
} from "@/lib/incidents";

const emptyForm: IncidentFormValues = {
  title: "",
  description: "",
  category: "",
  origin: "",
  branch: "",
};

const inputClass =
  "mt-2 block min-h-12 w-full rounded-lg border bg-white px-4 py-3 text-base text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-cyan-500";

function borderClass(hasError: boolean): string {
  return hasError ? "border-rose-400" : "border-slate-300";
}

interface FieldProps {
  id: IncidentFormField;
  label: string;
  error?: string;
  hint?: string;
  children: ReactNode;
}

function Field({ id, label, error, hint, children }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-semibold text-slate-800">
        {label} <span className="text-rose-600" aria-hidden="true">*</span>
      </label>
      {children}
      {hint && !error ? (
        <p id={`${id}-hint`} className="mt-1.5 text-sm text-slate-500">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} role="alert" className="mt-1.5 text-sm font-medium text-rose-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function describedBy(id: IncidentFormField, errors: IncidentFormErrors, hasHint = false) {
  if (errors[id]) return `${id}-error`;
  return hasHint ? `${id}-hint` : undefined;
}

export function IncidentForm() {
  const [values, setValues] = useState<IncidentFormValues>(emptyForm);
  const [errors, setErrors] = useState<IncidentFormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [created, setCreated] = useState<Incident | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  const isBranchOrigin = values.origin === "branch";

  function update<K extends IncidentFormField>(field: K, value: IncidentFormValues[K]) {
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
    setCreated(null);
  }

  function focusFirstError(fieldErrors: IncidentFormErrors) {
    const first = (Object.keys(emptyForm) as IncidentFormField[]).find(
      (field) => fieldErrors[field],
    );
    if (!first) return;
    const element = formRef.current?.querySelector<HTMLElement>(
      first === "origin" ? `input[name="origin"]` : `#${first}`,
    );
    element?.focus();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setFormError(null);
    setCreated(null);

    const clientErrors = validateIncidentForm(values);
    setErrors(clientErrors);
    if (Object.keys(clientErrors).length > 0) {
      setFormError("Completa los campos marcados antes de enviar.");
      focusFirstError(clientErrors);
      return;
    }

    setSubmitting(true);
    try {
      const incident = await createIncident({
        title: values.title.trim(),
        description: values.description.trim(),
        category: values.category as Exclude<IncidentFormValues["category"], "">,
        origin: values.origin as Exclude<IncidentFormValues["origin"], "">,
        branch: values.branch as Exclude<IncidentFormValues["branch"], "">,
        status: "open",
      });
      setValues(emptyForm);
      setErrors({});
      setCreated(incident);
    } catch (error) {
      const friendly = toFriendlyError(error, "registrar la incidencia");
      setErrors(friendly.fields);
      setFormError(friendly.message);
      focusFirstError(friendly.fields);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">
          Incidencias · Registro
        </p>
        <h1 className="mt-2 text-3xl font-bold text-slate-950">Registrar incidencia</h1>
        <p className="mt-2 text-sm text-slate-600">
          Paquetes perdidos, fallos de carrier, descuadres de inventario o
          devoluciones: todo queda registrado y trazable desde aquí.
        </p>
      </header>

      {created ? (
        <div
          role="status"
          className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-900"
        >
          <p className="font-semibold">
            Incidencia #{created.id} registrada como «{incidentStatusLabels[created.status]}».
          </p>
          <p className="mt-1 text-sm">
            «{created.title}» · {branchLabels[created.branch]}. El formulario está
            listo para otra incidencia.
          </p>
          <Link
            href="/incidents"
            className="mt-3 inline-flex min-h-11 items-center rounded-lg border border-emerald-300 bg-white px-4 text-sm font-semibold text-emerald-900 hover:bg-emerald-100"
          >
            Ver panel de incidencias
          </Link>
        </div>
      ) : null}

      {formError ? (
        <p
          role="alert"
          className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm font-medium text-rose-800"
        >
          {formError}
        </p>
      ) : null}

      <form
        ref={formRef}
        noValidate
        onSubmit={handleSubmit}
        aria-busy={submitting}
        className="space-y-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      >
        <Field
          id="title"
          label="Título"
          error={errors.title}
          hint={`Resumen breve, hasta ${TITLE_MAX_LENGTH} caracteres (${values.title.length}/${TITLE_MAX_LENGTH}).`}
        >
          <input
            id="title"
            name="title"
            type="text"
            maxLength={TITLE_MAX_LENGTH}
            value={values.title}
            onChange={(event) => update("title", event.target.value)}
            aria-invalid={Boolean(errors.title)}
            aria-describedby={describedBy("title", errors, true)}
            className={`${inputClass} ${borderClass(Boolean(errors.title))}`}
          />
        </Field>

        <Field id="description" label="Descripción" error={errors.description}>
          <textarea
            id="description"
            name="description"
            rows={4}
            value={values.description}
            onChange={(event) => update("description", event.target.value)}
            aria-invalid={Boolean(errors.description)}
            aria-describedby={describedBy("description", errors)}
            className={`${inputClass} ${borderClass(Boolean(errors.description))}`}
          />
        </Field>

        <Field
          id="category"
          label="Categoría"
          error={errors.category}
          hint={values.category ? incidentCategoryHints[values.category] : undefined}
        >
          <select
            id="category"
            name="category"
            value={values.category}
            onChange={(event) =>
              update("category", event.target.value as IncidentFormValues["category"])
            }
            aria-invalid={Boolean(errors.category)}
            aria-describedby={describedBy("category", errors, Boolean(values.category))}
            className={`${inputClass} ${borderClass(Boolean(errors.category))}`}
          >
            <option value="">Selecciona una categoría</option>
            {incidentCategories.map((category) => (
              <option key={category} value={category}>
                {incidentCategoryLabels[category]}
              </option>
            ))}
          </select>
        </Field>

        <fieldset aria-describedby={errors.origin ? "origin-error" : undefined}>
          <legend className="text-sm font-semibold text-slate-800">
            Origen <span className="text-rose-600" aria-hidden="true">*</span>
          </legend>
          <div className="mt-2 grid gap-3 sm:grid-cols-3">
            {incidentOrigins.map((origin) => {
              const selected = values.origin === origin;
              return (
                <label
                  key={origin}
                  className={`flex min-h-16 cursor-pointer flex-col justify-center rounded-lg border-2 px-4 py-3 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-cyan-500 ${
                    selected
                      ? "border-cyan-600 bg-cyan-50"
                      : errors.origin
                        ? "border-rose-300 bg-white"
                        : "border-slate-200 bg-white hover:border-slate-300"
                  }`}
                >
                  <input
                    type="radio"
                    name="origin"
                    value={origin}
                    checked={selected}
                    onChange={() => update("origin", origin)}
                    className="sr-only"
                  />
                  <span className="text-base font-semibold text-slate-900">
                    {incidentOriginLabels[origin]}
                  </span>
                  <span className="text-xs text-slate-500">{incidentOriginHints[origin]}</span>
                </label>
              );
            })}
          </div>
          {errors.origin ? (
            <p id="origin-error" role="alert" className="mt-1.5 text-sm font-medium text-rose-700">
              {errors.origin}
            </p>
          ) : null}
        </fieldset>

        <div
          className={
            isBranchOrigin
              ? "rounded-xl border-2 border-amber-400 bg-amber-50 p-4"
              : undefined
          }
        >
          <Field
            id="branch"
            label={isBranchOrigin ? "Sede desde la que reportas" : "Sede"}
            error={errors.branch}
            hint={
              isBranchOrigin
                ? "Estás reportando desde una sede concreta: confirma que es la correcta."
                : "Usa «Central» si no corresponde a una instalación concreta."
            }
          >
            <select
              id="branch"
              name="branch"
              value={values.branch}
              onChange={(event) =>
                update("branch", event.target.value as IncidentFormValues["branch"])
              }
              aria-invalid={Boolean(errors.branch)}
              aria-describedby={describedBy("branch", errors, true)}
              className={`${inputClass} ${
                isBranchOrigin && !errors.branch
                  ? "border-amber-500 font-semibold"
                  : borderClass(Boolean(errors.branch))
              }`}
            >
              <option value="">Selecciona una sede</option>
              {branches.map((branch) => (
                <option key={branch} value={branch}>
                  {branchLabels[branch]}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div>
          <p className="text-sm font-semibold text-slate-800">Estado</p>
          <p className="mt-2 inline-flex min-h-11 items-center rounded-lg bg-slate-100 px-4 text-base text-slate-700">
            {incidentStatusLabels.open}
          </p>
          <p className="mt-1.5 text-sm text-slate-500">
            Toda incidencia nueva empieza abierta; su estado se actualiza desde el panel.
          </p>
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex min-h-14 w-full items-center justify-center gap-3 rounded-lg bg-slate-900 px-6 text-base font-bold text-white hover:bg-slate-800 disabled:cursor-wait disabled:opacity-70"
        >
          {submitting ? (
            <>
              <span
                aria-hidden="true"
                className="h-5 w-5 animate-spin rounded-full border-2 border-white/40 border-t-white"
              />
              Registrando incidencia…
            </>
          ) : (
            "Registrar incidencia"
          )}
        </button>
      </form>
    </div>
  );
}
