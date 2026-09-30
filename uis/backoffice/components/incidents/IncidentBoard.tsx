"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/Panel";
import { ApiError } from "@/lib/api-client";
import {
  branchLabels,
  branches,
  fetchIncidents,
  formatIncidentDate,
  incidentCategories,
  incidentCategoryLabels,
  incidentOriginLabels,
  incidentOrigins,
  incidentStatusLabels,
  incidentStatuses,
  nextStatuses,
  slaCategories,
  toFriendlyError,
  updateIncidentStatus,
  type IncidentListItem,
  type IncidentFilters,
  type IncidentStatus,
} from "@/lib/incidents";

interface IncidentBoardProps {
  /** Se llama tras un cambio de estado confirmado por la API. */
  onChanged: () => void;
}

type ListState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; incidents: IncidentListItem[]; loadedAt: number };

interface Notice {
  tone: "success" | "error";
  message: string;
}

const emptyFilters: IncidentFilters = { status: "", origin: "", branch: "", category: "" };
const STALE_AFTER_MS = 24 * 60 * 60 * 1000;

const statusTone: Record<IncidentStatus, "info" | "warning" | "success" | "neutral"> = {
  open: "info",
  in_progress: "warning",
  resolved: "success",
  discarded: "neutral",
};

const selectClass =
  "mt-1 block min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900";

interface FilterSelectProps<V extends string> {
  label: string;
  value: V | "";
  options: readonly V[];
  labels: Record<V, string>;
  allLabel: string;
  onChange: (value: V | "") => void;
}

function FilterSelect<V extends string>({
  label,
  value,
  options,
  labels,
  allLabel,
  onChange,
}: FilterSelectProps<V>) {
  return (
    <label className="text-xs font-medium text-slate-600">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as V | "")}
        className={selectClass}
      >
        <option value="">{allLabel}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {labels[option]}
          </option>
        ))}
      </select>
    </label>
  );
}

export function IncidentBoard({ onChanged }: IncidentBoardProps) {
  const [filters, setFilters] = useState<IncidentFilters>(emptyFilters);
  const [slaOnly, setSlaOnly] = useState(false);
  const [state, setState] = useState<ListState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    let active = true;
    fetchIncidents(filters)
      .then((incidents) => {
        if (active) setState({ kind: "ready", incidents, loadedAt: Date.now() });
      })
      .catch((error: unknown) => {
        if (active) {
          setState({
            kind: "error",
            message: toFriendlyError(error, "cargar las incidencias").message,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [filters, attempt]);

  function reload() {
    setState({ kind: "loading" });
    setAttempt((value) => value + 1);
  }

  function changeFilter<K extends keyof IncidentFilters>(key: K, value: IncidentFilters[K]) {
    setState({ kind: "loading" });
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function clearFilters() {
    setSlaOnly(false);
    if (Object.values(filters).some(Boolean)) {
      setState({ kind: "loading" });
      setFilters(emptyFilters);
    }
  }

  function replaceIncident(id: number, patch: Partial<IncidentListItem>) {
    setState((current) =>
      current.kind === "ready"
        ? {
            ...current,
            incidents: current.incidents.map((item) =>
              item.id === id ? { ...item, ...patch } : item,
            ),
          }
        : current,
    );
  }

  async function changeStatus(incident: IncidentListItem, target: IncidentStatus) {
    const previous = incident.status;
    if (target === previous) return;
    setNotice(null);
    setPendingId(incident.id);
    replaceIncident(incident.id, { status: target });
    try {
      const updated = await updateIncidentStatus(incident.id, target);
      // La fila del listado solo guarda los campos del listado (sin `reported_by`).
      replaceIncident(incident.id, { status: updated.status });
      setNotice({
        tone: "success",
        message: `Incidencia #${incident.id} actualizada a «${incidentStatusLabels[updated.status]}».`,
      });
      onChanged();
    } catch (error) {
      replaceIncident(incident.id, { status: previous });
      const reason =
        error instanceof ApiError && error.status === 400
          ? `no se puede pasar de «${incidentStatusLabels[previous]}» a «${incidentStatusLabels[target]}».`
          : toFriendlyError(error, "actualizar el estado").message;
      setNotice({
        tone: "error",
        message: `Incidencia #${incident.id}: ${reason} Se mantiene «${incidentStatusLabels[previous]}».`,
      });
    } finally {
      setPendingId(null);
    }
  }

  const hasFilters = slaOnly || Object.values(filters).some(Boolean);
  const visible =
    state.kind === "ready"
      ? state.incidents.filter((item) => !slaOnly || slaCategories.has(item.category))
      : [];

  return (
    <section
      aria-labelledby="incident-list-title"
      className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="incident-list-title" className="text-lg font-semibold text-slate-900">
            Incidencias registradas
          </h2>
          <p className="mt-1 text-sm text-slate-500" aria-live="polite">
            {state.kind === "ready"
              ? `${visible.length} incidencias en la vista actual`
              : state.kind === "loading"
                ? "Cargando…"
                : "Sin datos"}
          </p>
        </div>
        <Link
          href="/incidents/new"
          className="inline-flex min-h-11 items-center rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-800"
        >
          Registrar incidencia
        </Link>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <FilterSelect
          label="Estado"
          value={filters.status}
          options={incidentStatuses}
          labels={incidentStatusLabels}
          allLabel="Todos"
          onChange={(value) => changeFilter("status", value)}
        />
        <FilterSelect
          label="Origen"
          value={filters.origin}
          options={incidentOrigins}
          labels={incidentOriginLabels}
          allLabel="Todos"
          onChange={(value) => changeFilter("origin", value)}
        />
        <FilterSelect
          label="Sede"
          value={filters.branch}
          options={branches}
          labels={branchLabels}
          allLabel="Todas"
          onChange={(value) => changeFilter("branch", value)}
        />
        <FilterSelect
          label="Categoría"
          value={filters.category}
          options={incidentCategories}
          labels={incidentCategoryLabels}
          allLabel="Todas"
          onChange={(value) => changeFilter("category", value)}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-4">
        <label className="inline-flex min-h-11 items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={slaOnly}
            onChange={(event) => setSlaOnly(event.target.checked)}
            className="h-5 w-5"
          />
          Solo impacto en SLA (paquete extraviado y carrier)
        </label>
        {hasFilters ? (
          <button
            type="button"
            onClick={clearFilters}
            className="min-h-11 text-sm font-medium text-cyan-800 underline underline-offset-4"
          >
            Limpiar filtros
          </button>
        ) : null}
      </div>

      {notice ? (
        <p
          role={notice.tone === "error" ? "alert" : "status"}
          className={`mt-4 rounded-lg border p-3 text-sm ${
            notice.tone === "error"
              ? "border-rose-200 bg-rose-50 text-rose-800"
              : "border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
        >
          {notice.message}
        </p>
      ) : null}

      <div className="mt-5">
        {state.kind === "loading" ? (
          <div aria-busy="true" className="space-y-2">
            <p className="sr-only" role="status">
              Cargando incidencias…
            </p>
            {Array.from({ length: 5 }, (_, index) => (
              <div key={index} className="h-14 animate-pulse rounded-lg bg-slate-100" />
            ))}
          </div>
        ) : null}

        {state.kind === "error" ? (
          <div
            role="alert"
            className="rounded-lg border border-rose-200 bg-rose-50 p-5 text-center text-sm text-rose-800"
          >
            <p>{state.message}</p>
            <button
              type="button"
              onClick={reload}
              className="mt-3 min-h-11 rounded-lg border border-rose-300 bg-white px-5 font-semibold hover:bg-rose-100"
            >
              Reintentar
            </button>
          </div>
        ) : null}

        {state.kind === "ready" && visible.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-600">
            {hasFilters ? (
              <>
                <p className="font-medium text-slate-800">
                  Ninguna incidencia coincide con los filtros aplicados.
                </p>
                <button
                  type="button"
                  onClick={clearFilters}
                  className="mt-3 min-h-11 rounded-lg border border-slate-300 px-4 font-semibold hover:bg-slate-50"
                >
                  Limpiar filtros
                </button>
              </>
            ) : (
              <>
                <p className="font-medium text-slate-800">Todavía no hay incidencias registradas.</p>
                <p className="mt-1">Cuando alguien registre la primera, aparecerá aquí.</p>
              </>
            )}
          </div>
        ) : null}

        {state.kind === "ready" && visible.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-3">Incidencia</th>
                  <th className="px-3 py-3">Categoría</th>
                  <th className="px-3 py-3">Origen</th>
                  <th className="px-3 py-3">Sede</th>
                  <th className="px-3 py-3">Creada</th>
                  <th className="px-3 py-3">Estado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visible.map((incident) => {
                  const options = [incident.status, ...nextStatuses[incident.status]];
                  const isFinal = options.length === 1;
                  const isStale =
                    (incident.status === "open" || incident.status === "in_progress") &&
                    state.loadedAt - new Date(incident.created_at).getTime() > STALE_AFTER_MS;
                  return (
                    <tr key={incident.id} className="align-top">
                      <td className="max-w-md px-3 py-3">
                        <p className="font-semibold text-slate-900">
                          <span className="mr-1 text-slate-400">#{incident.id}</span>
                          {incident.title}
                        </p>
                        {incident.description !== incident.title ? (
                          <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                            {incident.description}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex flex-col items-start gap-1">
                          <span>{incidentCategoryLabels[incident.category]}</span>
                          {slaCategories.has(incident.category) ? (
                            <Badge tone="danger">Impacto SLA</Badge>
                          ) : null}
                        </div>
                      </td>
                      <td className="px-3 py-3">{incidentOriginLabels[incident.origin]}</td>
                      <td className="px-3 py-3">{branchLabels[incident.branch]}</td>
                      <td className="whitespace-nowrap px-3 py-3">
                        <span className="block">{formatIncidentDate(incident.created_at)}</span>
                        {isStale ? <Badge tone="warning">Más de 24 h sin cerrar</Badge> : null}
                      </td>
                      <td className="px-3 py-3">
                        {isFinal ? (
                          <Badge tone={statusTone[incident.status]}>
                            {incidentStatusLabels[incident.status]}
                          </Badge>
                        ) : (
                          <label className="block">
                            <span className="sr-only">Estado de la incidencia #{incident.id}</span>
                            <select
                              value={incident.status}
                              disabled={pendingId === incident.id}
                              onChange={(event) =>
                                void changeStatus(incident, event.target.value as IncidentStatus)
                              }
                              className={`${selectClass} mt-0 min-w-36 disabled:cursor-wait disabled:opacity-60`}
                            >
                              {options.map((option) => (
                                <option key={option} value={option}>
                                  {incidentStatusLabels[option]}
                                </option>
                              ))}
                            </select>
                            {pendingId === incident.id ? (
                              <span className="mt-1 block text-xs text-slate-500">Guardando…</span>
                            ) : null}
                          </label>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </section>
  );
}
