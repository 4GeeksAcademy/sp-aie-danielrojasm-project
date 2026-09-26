"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import {
  countryOptions,
  emptyApplication,
  priorityOptions,
  serviceOptions,
  validateApplication,
  validateApplicationField,
  type ApplicationErrors,
  type ApplicationField,
  type ApplicationFormValues,
  type ServiceInterest,
} from "@/lib/application-form";
import {
  FieldError,
  Fieldset,
  FormField,
  inputBaseClass,
  inputStateClass,
} from "@/components/forms/FormField";

type TextField = Exclude<ApplicationField, "services" | "privacyAccepted">;

interface TextInputConfig {
  name: TextField;
  label: string;
  type: "text" | "email" | "tel" | "number" | "url" | "date";
  required: boolean;
  placeholder?: string;
  autoComplete?: string;
  min?: number;
  max?: number;
  step?: number;
}

const contactFields: TextInputConfig[] = [
  { name: "fullName", label: "Nombre completo", type: "text", required: true, placeholder: "Ej. Laura Mendoza", autoComplete: "name" },
  { name: "jobTitle", label: "Cargo", type: "text", required: true, placeholder: "Ej. Head of Operations", autoComplete: "organization-title" },
  { name: "email", label: "Email corporativo", type: "email", required: true, placeholder: "nombre@empresa.com", autoComplete: "email" },
  { name: "phone", label: "Teléfono", type: "tel", required: true, placeholder: "+34 600 123 456", autoComplete: "tel" },
];

const operationFields: TextInputConfig[] = [
  { name: "monthlyShipments", label: "Volumen mensual de envíos", type: "number", required: true, placeholder: "Ej. 12000", min: 100, max: 2_000_000 },
  { name: "returnsRate", label: "Tasa de devoluciones (%)", type: "number", required: true, placeholder: "Ej. 22.5", min: 0, max: 100, step: 0.1 },
  { name: "goLiveDate", label: "Fecha objetivo de implementación", type: "date", required: true },
];

export function ApplicationForm() {
  const [values, setValues] = useState<ApplicationFormValues>(emptyApplication);
  const [errors, setErrors] = useState<ApplicationErrors>({});
  const [touched, setTouched] = useState<Partial<Record<ApplicationField, boolean>>>({});
  const [submitted, setSubmitted] = useState(false);

  function updateValues(next: ApplicationFormValues, field: ApplicationField) {
    setValues(next);
    setSubmitted(false);
    if (touched[field]) {
      setErrors((prev) => ({
        ...prev,
        [field]: validateApplicationField(field, next) ?? undefined,
      }));
    }
  }

  function handleTextChange(
    event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
  ) {
    const field = event.target.name as TextField;
    updateValues({ ...values, [field]: event.target.value }, field);
  }

  function handleBlur(field: ApplicationField) {
    setTouched((prev) => ({ ...prev, [field]: true }));
    setErrors((prev) => ({
      ...prev,
      [field]: validateApplicationField(field, values) ?? undefined,
    }));
  }

  function toggleService(service: ServiceInterest) {
    const services = values.services.includes(service)
      ? values.services.filter((item) => item !== service)
      : [...values.services, service];
    setTouched((prev) => ({ ...prev, services: true }));
    const next = { ...values, services };
    setValues(next);
    setSubmitted(false);
    setErrors((prev) => ({
      ...prev,
      services: validateApplicationField("services", next) ?? undefined,
    }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = validateApplication(values);
    setErrors(nextErrors);
    setTouched(
      Object.fromEntries(Object.keys(values).map((key) => [key, true])),
    );

    const firstInvalid = Object.keys(nextErrors)[0];
    if (firstInvalid) {
      document.getElementById(firstInvalid)?.focus();
      return;
    }

    setSubmitted(true);
    setValues(emptyApplication);
    setTouched({});
  }

  function handleReset() {
    setValues(emptyApplication);
    setErrors({});
    setTouched({});
    setSubmitted(false);
  }

  function renderInput(config: TextInputConfig) {
    const error = errors[config.name];
    return (
      <FormField
        key={config.name}
        id={config.name}
        label={config.label}
        required={config.required}
        error={error}
      >
        <input
          id={config.name}
          name={config.name}
          type={config.type}
          value={values[config.name]}
          onChange={handleTextChange}
          onBlur={() => handleBlur(config.name)}
          placeholder={config.placeholder}
          autoComplete={config.autoComplete}
          min={config.min}
          max={config.max}
          step={config.step}
          required={config.required}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${config.name}-error` : undefined}
          className={`${inputBaseClass} ${inputStateClass(Boolean(error))}`}
        />
      </FormField>
    );
  }

  return (
    <>
      {submitted ? (
        <div
          className="mb-6 rounded-lg border border-emerald-300/40 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100"
          role="status"
          aria-live="polite"
        >
          Aplicación enviada correctamente. Nuestro equipo revisará tus datos y
          te contactará en menos de 48 horas.
        </div>
      ) : null}

      <form
        onSubmit={handleSubmit}
        onReset={handleReset}
        noValidate
        className="space-y-8 rounded-2xl border border-slate-700 bg-slate-900/80 p-6 sm:p-8"
        aria-describedby="form-instructions"
      >
        <p id="form-instructions" className="text-sm text-slate-300">
          Los campos marcados con <span aria-hidden="true">*</span> son
          obligatorios.
        </p>

        <Fieldset legend="Datos de contacto">
          <div className="grid gap-5 md:grid-cols-2">
            {contactFields.map(renderInput)}
          </div>
        </Fieldset>

        <Fieldset legend="Datos de empresa">
          <div className="grid gap-5 md:grid-cols-2">
            {renderInput({ name: "companyName", label: "Nombre de empresa", type: "text", required: true, placeholder: "Ej. Urban Retail Labs", autoComplete: "organization" })}
            <FormField id="country" label="País principal de operación" required error={errors.country}>
              <select
                id="country"
                name="country"
                value={values.country}
                onChange={handleTextChange}
                onBlur={() => handleBlur("country")}
                aria-invalid={errors.country ? true : undefined}
                aria-describedby={errors.country ? "country-error" : undefined}
                className={`${inputBaseClass} ${inputStateClass(Boolean(errors.country))}`}
              >
                <option value="">Selecciona una opción</option>
                {countryOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </FormField>
            {renderInput({ name: "warehouseCount", label: "Número de almacenes activos", type: "number", required: true, placeholder: "Ej. 3", min: 1, max: 50 })}
            {renderInput({ name: "website", label: "Sitio web de empresa", type: "url", required: false, placeholder: "https://tuempresa.com" })}
          </div>
        </Fieldset>

        <Fieldset legend="Datos de operación logística">
          <div className="grid gap-5 md:grid-cols-2">
            {operationFields.map(renderInput)}
            <FormField id="priority" label="Prioridad del proyecto" required error={errors.priority}>
              <select
                id="priority"
                name="priority"
                value={values.priority}
                onChange={handleTextChange}
                onBlur={() => handleBlur("priority")}
                aria-invalid={errors.priority ? true : undefined}
                aria-describedby={errors.priority ? "priority-error" : undefined}
                className={`${inputBaseClass} ${inputStateClass(Boolean(errors.priority))}`}
              >
                <option value="">Selecciona una opción</option>
                {priorityOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </FormField>
          </div>

          <div
            role="group"
            aria-labelledby="services-label"
            aria-describedby={errors.services ? "services-error" : undefined}
          >
            <p id="services-label" className="mb-3 text-sm font-semibold text-slate-100">
              Servicios de interés * (elige al menos uno)
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              {serviceOptions.map((option) => (
                <label
                  key={option.value}
                  className="flex items-start gap-3 rounded-lg border border-slate-700 bg-slate-950 p-3"
                >
                  <input
                    id={option.value === "inventario" ? "services" : undefined}
                    type="checkbox"
                    name="services"
                    value={option.value}
                    checked={values.services.includes(option.value)}
                    onChange={() => toggleService(option.value)}
                    className="mt-1 h-4 w-4 accent-cyan-300"
                  />
                  <span className="text-sm text-slate-200">{option.label}</span>
                </label>
              ))}
            </div>
            <FieldError id="services-error" message={errors.services} />
          </div>

          <FormField id="mainPain" label="Principal problema a resolver" required error={errors.mainPain}>
            <textarea
              id="mainPain"
              name="mainPain"
              rows={4}
              value={values.mainPain}
              onChange={handleTextChange}
              onBlur={() => handleBlur("mainPain")}
              placeholder="Describe brevemente dónde tienes más fricción: inventario, entregas, devoluciones o CX."
              aria-invalid={errors.mainPain ? true : undefined}
              aria-describedby={errors.mainPain ? "mainPain-error" : undefined}
              className={`${inputBaseClass} ${inputStateClass(Boolean(errors.mainPain))}`}
            />
          </FormField>
        </Fieldset>

        <Fieldset legend="Consentimiento">
          <label className="flex items-start gap-3 rounded-lg border border-slate-700 bg-slate-950 p-4">
            <input
              id="privacyAccepted"
              name="privacyAccepted"
              type="checkbox"
              checked={values.privacyAccepted}
              onChange={(event) =>
                updateValues(
                  { ...values, privacyAccepted: event.target.checked },
                  "privacyAccepted",
                )
              }
              onBlur={() => handleBlur("privacyAccepted")}
              aria-invalid={errors.privacyAccepted ? true : undefined}
              aria-describedby={errors.privacyAccepted ? "privacyAccepted-error" : undefined}
              className="mt-1 h-4 w-4 accent-cyan-300"
            />
            <span className="text-sm text-slate-200">
              Acepto el tratamiento de mis datos para que TrackFlow contacte
              conmigo sobre esta aplicación. *
            </span>
          </label>
          <FieldError id="privacyAccepted-error" message={errors.privacyAccepted} />
        </Fieldset>

        <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
          <button
            type="reset"
            className="inline-flex items-center justify-center rounded-lg border border-slate-500 px-6 py-3 font-semibold text-slate-100 hover:border-slate-300 hover:text-white"
          >
            Limpiar formulario
          </button>
          <button
            type="submit"
            className="inline-flex items-center justify-center rounded-lg bg-cyan-300 px-6 py-3 font-bold text-slate-950 hover:bg-cyan-200"
          >
            Enviar aplicación
          </button>
        </div>
      </form>
    </>
  );
}
