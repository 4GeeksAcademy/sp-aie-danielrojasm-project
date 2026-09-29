"use client";

import { useState, type DragEvent, type FormEvent } from "react";
import { KpiCard, Panel } from "@/components/ui/Panel";
import {
  INCIDENT_CATEGORY_LABELS,
  INCIDENT_STATUS_LABELS,
  INVALID_REASON_LABELS,
  type IncidentAnalysisSummary,
  type IncidentCategory,
  type IncidentStatus,
} from "@/lib/incident-analysis";

const SATISFACTION_LABELS = [
  "Muy insatisfecho",
  "Insatisfecho",
  "Neutral",
  "Satisfecho",
  "Muy satisfecho",
];

function getErrorMessage(payload: unknown): string {
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = payload.detail;
    if (typeof detail === "string") return detail;
  }
  return "No se pudo completar la solicitud al servicio de análisis.";
}

export function IncidentAnalysis() {
  const [file, setFile] = useState<File | null>(null);
  const [summary, setSummary] = useState<IncidentAnalysisSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  function selectFile(selectedFile: File | null) {
    setFile(selectedFile);
    setSummary(null);
    setError(null);
    setExportError(null);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDragging(false);
    selectFile(event.dataTransfer.files.item(0));
  }

  async function handleAnalyze(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;

    setIsAnalyzing(true);
    setError(null);
    setExportError(null);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("/api/incidents/analyze", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(getErrorMessage(await response.json().catch(() => null)));
      }
      setSummary((await response.json()) as IncidentAnalysisSummary);
    } catch (requestError) {
      setError(
        requestError instanceof TypeError
          ? "No se pudo conectar con la API. Comprueba que el servicio esté activo."
          : requestError instanceof Error
            ? requestError.message
            : "No se pudo analizar el fichero.",
      );
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function handleExport() {
    setIsExporting(true);
    setExportError(null);
    try {
      const response = await fetch(
        "/api/incidents/results/export",
      );
      if (!response.ok) {
        throw new Error(getErrorMessage(await response.json().catch(() => null)));
      }
      const fileBlob = await response.blob();
      const objectUrl = URL.createObjectURL(fileBlob);
      const downloadLink = document.createElement("a");
      downloadLink.href = objectUrl;
      downloadLink.download = "incidents-results.csv";
      downloadLink.click();
      URL.revokeObjectURL(objectUrl);
    } catch (requestError) {
      setExportError(
        requestError instanceof TypeError
          ? "No se pudo conectar con la API para descargar los resultados."
          : requestError instanceof Error
            ? requestError.message
            : "No se pudieron descargar los resultados.",
      );
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header>
        <p className="text-sm font-semibold text-cyan-800">Experiencia del cliente</p>
        <h1 className="mt-1 text-2xl font-bold text-slate-900">
          Análisis de incidencias
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Resumen agregado de incidencias de clientes para el equipo de CX.
        </p>
      </header>

      <Panel
        title="Cargar fichero CSV"
        description="El análisis se realiza internamente. No se muestran ni exportan datos personales."
      >
        <form className="space-y-4" onSubmit={handleAnalyze}>
          <label
            htmlFor="incident-csv"
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setIsDragging(false);
              }
            }}
            onDrop={handleDrop}
            className={`flex min-h-32 cursor-pointer flex-col items-center justify-center border-2 border-dashed px-5 py-6 text-center transition-colors ${
              isDragging
                ? "border-cyan-700 bg-cyan-50"
                : "border-slate-300 bg-slate-50 hover:border-cyan-700 hover:bg-cyan-50/60"
            }`}
          >
            <span className="text-sm font-semibold text-slate-800">
              {file ? file.name : "Suelta el CSV aquí o selecciónalo"}
            </span>
            <span className="mt-1 text-xs text-slate-500">
              {file
                ? `${(file.size / 1024).toFixed(1)} KB`
                : "Formato requerido: .csv"}
            </span>
            <input
              id="incident-csv"
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={(event) =>
                selectFile(event.currentTarget.files?.item(0) ?? null)
              }
            />
          </label>
          <button
            type="submit"
            disabled={!file || isAnalyzing}
            className="inline-flex min-h-10 items-center justify-center bg-cyan-800 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-900 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {isAnalyzing ? "Analizando…" : "Analizar fichero"}
          </button>
        </form>
        {error ? (
          <p role="alert" className="mt-4 text-sm font-medium text-rose-700">
            {error}
          </p>
        ) : null}
      </Panel>

      {summary ? (
        <>
          <section aria-labelledby="incident-summary-title" className="space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 id="incident-summary-title" className="text-lg font-semibold">
                  Resumen del análisis
                </h2>
                <p className="text-sm text-slate-500">
                  Métricas calculadas solo sobre registros válidos.
                </p>
              </div>
              <button
                type="button"
                onClick={handleExport}
                disabled={isExporting}
                className="min-h-10 border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50 disabled:cursor-wait disabled:opacity-60"
              >
                {isExporting ? "Preparando CSV…" : "Descargar resultados CSV"}
              </button>
            </div>
            {exportError ? (
              <p role="alert" className="text-sm font-medium text-rose-700">
                {exportError}
              </p>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <KpiCard
                label="Registros totales"
                value={String(summary.total_records)}
                hint="Filas procesadas"
              />
              <KpiCard
                label="Registros válidos"
                value={String(summary.valid_records)}
                hint="Incluidos en los desgloses"
              />
              <KpiCard
                label="Registros inválidos"
                value={String(summary.invalid_records)}
                hint="Excluidos de las métricas"
                tone={summary.invalid_records > 0 ? "warning" : "default"}
              />
              <KpiCard
                label="Satisfacción media"
                value={
                  summary.average_satisfaction === null
                    ? "N/D"
                    : `${summary.average_satisfaction.toFixed(2)} / 5`
                }
                hint={`${summary.scored_closed_incidents} casos cerrados con puntuación`}
              />
            </div>
          </section>

          <div className="grid gap-6 xl:grid-cols-2">
            <Panel title="Incidencias por categoría">
              <ul className="space-y-4">
                {(Object.keys(INCIDENT_CATEGORY_LABELS) as IncidentCategory[]).map(
                  (category) => {
                    const value = summary.categories[category];
                    return (
                      <li key={category}>
                        <div className="flex justify-between gap-3 text-sm">
                          <span className="font-medium">
                            {INCIDENT_CATEGORY_LABELS[category]}
                            <span className="ml-2 font-mono text-xs text-slate-500">
                              {category}
                            </span>
                          </span>
                          <span className="shrink-0 tabular-nums text-slate-600">
                            {value.count} · {value.percentage.toFixed(1)}%
                          </span>
                        </div>
                        <div
                          className="mt-2 h-2 bg-slate-100"
                          role="img"
                          aria-label={`${value.percentage.toFixed(1)} por ciento`}
                        >
                          <div
                            className="h-full bg-cyan-700"
                            style={{ width: `${value.percentage}%` }}
                          />
                        </div>
                      </li>
                    );
                  },
                )}
              </ul>
            </Panel>

            <Panel title="Incidencias por estado">
              <dl className="divide-y divide-slate-100">
                {(Object.keys(INCIDENT_STATUS_LABELS) as IncidentStatus[]).map(
                  (status) => (
                    <div
                      key={status}
                      className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                    >
                      <dt>
                        <span className="block text-sm font-medium">
                          {INCIDENT_STATUS_LABELS[status]}
                        </span>
                        <span className="font-mono text-xs text-slate-500">
                          {status}
                        </span>
                      </dt>
                      <dd className="text-right tabular-nums">
                        <span className="block font-semibold">
                          {summary.statuses[status].count}
                        </span>
                        <span className="text-xs text-slate-500">
                          {summary.statuses[status].percentage.toFixed(1)}%
                        </span>
                      </dd>
                    </div>
                  ),
                )}
              </dl>
            </Panel>

            <Panel title="Puntuaciones en casos cerrados">
              <p className="mb-4 text-sm text-slate-600">
                {summary.scored_closed_incidents} de {summary.closed_incidents} casos
                cerrados tienen puntuación registrada.
              </p>
              <ol className="divide-y divide-slate-100">
                {SATISFACTION_LABELS.map((label, index) => {
                  const score = String(index + 1) as "1" | "2" | "3" | "4" | "5";
                  return (
                    <li
                      key={score}
                      className="flex justify-between gap-3 py-2 text-sm first:pt-0 last:pb-0"
                    >
                      <span>
                        <span className="mr-2 font-semibold tabular-nums">{score}</span>
                        {label}
                      </span>
                      <span className="tabular-nums text-slate-600">
                        {summary.satisfaction_scores[score]}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </Panel>

            <Panel title="Incidencias por país">
              <dl className="divide-y divide-slate-100">
                {(["US", "ES"] as const).map((country) => (
                  <div
                    key={country}
                    className="flex justify-between gap-4 py-3 text-sm first:pt-0 last:pb-0"
                  >
                    <dt className="font-medium">{country}</dt>
                    <dd className="tabular-nums text-slate-600">
                      {summary.countries[country].count} · {summary.countries[country].percentage.toFixed(1)}%
                    </dd>
                  </div>
                ))}
              </dl>
            </Panel>
          </div>

          <Panel title="Calidad de los registros">
            {summary.invalid_records === 0 ? (
              <p className="text-sm font-medium text-emerald-800">
                No se detectaron registros inválidos.
              </p>
            ) : (
              <div>
                <p className="mb-3 text-sm text-slate-700">
                  {summary.invalid_records} registros se excluyeron del análisis.
                  Un mismo registro puede activar más de una regla.
                </p>
                <ul className="grid gap-x-8 sm:grid-cols-2">
                  {Object.entries(summary.invalid_breakdown)
                    .filter(([, value]) => value.count > 0)
                    .map(([key, value]) => (
                      <li
                        key={key}
                        className="flex justify-between gap-3 border-t border-slate-100 py-2 text-sm"
                      >
                        <span>{INVALID_REASON_LABELS[key] ?? value.label}</span>
                        <span className="shrink-0 font-semibold tabular-nums">
                          {value.count}
                        </span>
                      </li>
                    ))}
                </ul>
              </div>
            )}
          </Panel>
        </>
      ) : null}
    </div>
  );
}