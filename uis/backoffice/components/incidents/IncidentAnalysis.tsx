"use client";

import dynamic from "next/dynamic";
import { useState, type DragEvent, type FormEvent } from "react";
import { Panel } from "@/components/ui/Panel";
import type { IncidentAnalysisSummary } from "@/lib/incident-analysis";
import { getUserMessage, requestBlob, requestJson } from "@/lib/api-client";

// Los resultados solo se pintan tras analizar un CSV: su código se pide en ese
// momento y no en la carga inicial de la vista.
const IncidentAnalysisResults = dynamic(
  () => import("@/components/incidents/IncidentAnalysisResults").then((mod) => mod.IncidentAnalysisResults),
  {
    loading: () => (
      <div aria-busy="true" className="space-y-3">
        <p className="sr-only" role="status">
          Preparando resultados…
        </p>
        <div className="h-24 animate-pulse bg-slate-200" />
        <div className="h-64 animate-pulse bg-slate-200" />
      </div>
    ),
  },
);

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
      const result = await requestJson<IncidentAnalysisSummary>(
        "/api/incidents/analyze",
        { method: "POST", body: formData },
        "No se pudo analizar el fichero. Comprueba que sea un CSV de incidencias.",
      );
      setSummary(result);
    } catch (requestError) {
      setError(
        getUserMessage(requestError, "No se pudo analizar el fichero. Inténtalo de nuevo."),
      );
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function handleExport() {
    setIsExporting(true);
    setExportError(null);
    let objectUrl: string | null = null;
    try {
      const fileBlob = await requestBlob(
        "/api/incidents/results/export",
        {},
        "No se pudieron descargar los resultados.",
      );
      objectUrl = URL.createObjectURL(fileBlob);
      const downloadLink = document.createElement("a");
      downloadLink.href = objectUrl;
      downloadLink.download = "incidents-results.csv";
      downloadLink.click();
    } catch (requestError) {
      setExportError(
        getUserMessage(requestError, "No se pudieron descargar los resultados. Inténtalo de nuevo."),
      );
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
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
        <form id="incident-analysis-form" className="space-y-4" onSubmit={handleAnalyze}>
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
          <div role="alert" className="mt-4 flex flex-wrap items-center gap-3 text-sm font-medium text-rose-700">
            <span>{error}</span>
            {file ? (
              <button
                type="submit"
                form="incident-analysis-form"
                disabled={isAnalyzing}
                className="min-h-9 border border-rose-300 bg-white px-3 font-semibold text-rose-800 hover:bg-rose-50"
              >
                Reintentar
              </button>
            ) : null}
            <span className="font-normal text-slate-600">
              o selecciona otro fichero.
            </span>
          </div>
        ) : null}
      </Panel>

      {summary ? (
        <IncidentAnalysisResults
          summary={summary}
          onExport={handleExport}
          isExporting={isExporting}
          exportError={exportError}
        />
      ) : null}
    </div>
  );
}