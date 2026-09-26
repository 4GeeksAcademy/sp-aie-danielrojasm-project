"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import CandidateForm from "@/components/CandidateForm";
import {
  STAGE_OPTIONS,
  STATUS_OPTIONS,
  TRACKFLOW_POSITION,
  getStageLabel,
  getStatusLabel,
} from "@/lib/domain";
import { createRecord, fetchRecords } from "@/services/recordsApi";
import {
  Candidate,
  CandidateFormValues,
  CandidateStage,
  CandidateStatus,
} from "@/types/candidate";

function normalizeStatusFilter(value: string | null): CandidateStatus | "" {
  if (!value) {
    return "";
  }

  if (STATUS_OPTIONS.includes(value as CandidateStatus)) {
    return value as CandidateStatus;
  }

  return "";
}

function normalizeStageFilter(value: string | null): CandidateStage | "" {
  if (!value) {
    return "";
  }

  if (STAGE_OPTIONS.includes(value as CandidateStage)) {
    return value as CandidateStage;
  }

  return "";
}

export default function CandidatesListClient() {
  const [records, setRecords] = useState<Candidate[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();

  const statusFilter = normalizeStatusFilter(searchParams.get("status"));
  const stageFilter = normalizeStageFilter(searchParams.get("stage"));
  const searchFilter = (searchParams.get("q") || "").trim();

  useEffect(() => {
    async function loadRecords() {
      setIsLoading(true);
      setErrorMessage(null);

      try {
        const candidates = await fetchRecords();
        setRecords(candidates);
      } catch (error) {
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "No se pudo cargar el listado de candidaturas.",
        );
      } finally {
        setIsLoading(false);
      }
    }

    void loadRecords();
  }, []);

  const filteredRecords = useMemo(() => {
    return records.filter((candidate) => {
      const matchesStatus = statusFilter ? candidate.status === statusFilter : true;
      const matchesStage = stageFilter ? candidate.stage === stageFilter : true;
      const matchesSearch = searchFilter
        ? `${candidate.name} ${candidate.email}`
            .toLowerCase()
            .includes(searchFilter.toLowerCase())
        : true;

      return matchesStatus && matchesStage && matchesSearch;
    });
  }, [records, searchFilter, stageFilter, statusFilter]);

  const updateQueryParam = (name: string, value: string) => {
    const currentParams = new URLSearchParams(searchParams.toString());

    if (value) {
      currentParams.set(name, value);
    } else {
      currentParams.delete(name);
    }

    const queryString = currentParams.toString();
    router.replace(queryString ? `${pathname}?${queryString}` : pathname);
  };

  const handleCreateCandidate = async (
    values: CandidateFormValues,
  ): Promise<Candidate> => {
    const createdCandidate = await createRecord(values);
    setRecords((previousRecords) => [createdCandidate, ...previousRecords]);
    return createdCandidate;
  };

  return (
    <div className="mx-auto grid w-full max-w-6xl gap-6 px-4 py-6 md:px-6">
      <header className="rounded-2xl border border-cyan-300/20 bg-slate-950/85 p-5 text-slate-100 shadow-lg shadow-cyan-900/20 backdrop-blur">
        <p className="text-xs uppercase tracking-[0.2em] text-cyan-200">
          TrackFlow · People & Talent
        </p>
        <h1 className="mt-1 text-2xl font-black text-white">Talent Pipeline Tracker</h1>
        <p className="mt-2 text-sm text-slate-300">
          Proceso activo: {TRACKFLOW_POSITION} · Sede Zaragoza
        </p>
      </header>

      <section className="rounded-2xl border border-slate-700 bg-slate-900/80 p-4 shadow-lg shadow-black/20">
        <h2 className="mb-3 text-lg font-bold text-cyan-100">Listado de candidaturas</h2>

        <div className="grid gap-3 md:grid-cols-3">
          <label className="grid gap-1 text-sm font-semibold text-slate-200">
            Buscar por nombre o email
            <input
              className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
              value={searchFilter}
              onChange={(event) => updateQueryParam("q", event.target.value)}
              placeholder="Ej: laura@correo.com"
            />
          </label>

          <label className="grid gap-1 text-sm font-semibold text-slate-200">
            Filtrar por estado
            <select
              className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
              value={statusFilter}
              onChange={(event) => updateQueryParam("status", event.target.value)}
            >
              <option value="">Todos</option>
              {STATUS_OPTIONS.map((statusValue) => (
                <option key={statusValue} value={statusValue}>
                  {getStatusLabel(statusValue)}
                </option>
              ))}
            </select>
          </label>

          <label className="grid gap-1 text-sm font-semibold text-slate-200">
            Filtrar por etapa
            <select
              className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30"
              value={stageFilter}
              onChange={(event) => updateQueryParam("stage", event.target.value)}
            >
              <option value="">Todas</option>
              {STAGE_OPTIONS.map((stageValue) => (
                <option key={stageValue} value={stageValue}>
                  {getStageLabel(stageValue)}
                </option>
              ))}
            </select>
          </label>
        </div>

        {isLoading && (
          <p className="mt-4 rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-3 py-2 text-sm text-cyan-100">
            Cargando candidaturas...
          </p>
        )}

        {errorMessage && (
          <p className="mt-4 rounded-lg border border-rose-300/40 bg-rose-400/10 px-3 py-2 text-sm text-rose-200">
            Error: {errorMessage}
          </p>
        )}

        {!isLoading && !errorMessage && (
          <div className="mt-4 overflow-x-auto rounded-lg border border-slate-700">
            <table className="min-w-full divide-y divide-slate-700 text-sm">
              <thead className="bg-slate-950">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold text-cyan-100">Nombre</th>
                  <th className="px-3 py-2 text-left font-semibold text-cyan-100">Puesto</th>
                  <th className="px-3 py-2 text-left font-semibold text-cyan-100">Estado</th>
                  <th className="px-3 py-2 text-left font-semibold text-cyan-100">Etapa</th>
                  <th className="px-3 py-2 text-left font-semibold text-cyan-100">Detalle</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700 bg-slate-900/70">
                {filteredRecords.length === 0 ? (
                  <tr>
                    <td className="px-3 py-4 text-slate-300" colSpan={5}>
                      No hay candidaturas que cumplan con los filtros actuales.
                    </td>
                  </tr>
                ) : (
                  filteredRecords.map((candidate) => (
                    <tr key={candidate.id}>
                      <td className="px-3 py-2 text-slate-100">{candidate.name}</td>
                      <td className="px-3 py-2 text-slate-300">{candidate.position}</td>
                      <td className="px-3 py-2 text-slate-300">
                        {getStatusLabel(candidate.status)}
                      </td>
                      <td className="px-3 py-2 text-slate-300">
                        {getStageLabel(candidate.stage)}
                      </td>
                      <td className="px-3 py-2">
                        <Link
                          href={`/candidates/${candidate.id}`}
                          className="text-sm font-semibold text-cyan-200 underline hover:text-cyan-100"
                        >
                          Ver candidatura
                        </Link>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <CandidateForm
        mode="create"
        title="Registrar nueva candidatura"
        submitLabel="Registrar candidatura"
        onSubmit={handleCreateCandidate}
      />
    </div>
  );
}
