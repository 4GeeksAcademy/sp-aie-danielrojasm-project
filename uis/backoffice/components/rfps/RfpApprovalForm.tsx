"use client";

import { useState, type FormEvent } from "react";
import { getUserMessage } from "@/lib/api-client";
import {
  rfpComplianceRuleLabels,
  rfpDecisionLabels,
  submitRfpDecision,
  validateRfpDecision,
  type RfpDecision,
  type RfpDepartmentId,
  type RfpPendingReview,
} from "@/lib/rfps";

const SUBMIT_FALLBACK_ERROR = "No se pudo registrar la decisión.";

interface RfpApprovalFormProps {
  ticketId: string;
  departmentId: RfpDepartmentId;
  review: RfpPendingReview;
  /** La decisión quedó encolada: el detalle se recarga para mostrar cómo la aplica el worker. */
  onSubmitted: () => void;
}

/** Decisión del responsable de una sección: aprobar, pedir cambios o rechazar (Parte 3). */
export function RfpApprovalForm({ ticketId, departmentId, review, onSubmitted }: RfpApprovalFormProps) {
  const [decision, setDecision] = useState<RfpDecision>("approve");
  const [comment, setComment] = useState("");
  const [capacity, setCapacity] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const formId = `rfp-approval-${departmentId}`;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const invalid = validateRfpDecision(decision, comment);
    const committed = capacity.trim() ? Number(capacity) : undefined;
    if (invalid) return setError(invalid);
    if (committed !== undefined && (!Number.isInteger(committed) || committed <= 0)) {
      return setError("La capacidad tiene que ser un número entero de pedidos al mes.");
    }
    setSending(true);
    setError("");
    try {
      await submitRfpDecision(ticketId, departmentId, {
        decision,
        review_round: review.review_round,
        comment: comment.trim(),
        ...(committed !== undefined && decision === "approve" ? { committed_monthly_capacity: committed } : {}),
      });
      onSubmitted();
    } catch (caught) {
      setError(getUserMessage(caught, SUBMIT_FALLBACK_ERROR));
      setSending(false);
    }
  };

  const remaining = review.max_rounds - review.revisions;
  return (
    <form onSubmit={submit} aria-labelledby={`${formId}-title`} className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <h4 id={`${formId}-title`} className="text-sm font-semibold text-amber-900">
        Decisión de {review.approver} · revisión {review.review_round}
      </h4>
      <ul className="mt-2 space-y-1 text-sm text-amber-900">
        <li>
          Evaluación automática:{" "}
          {review.evaluation_pass === false
            ? `no superada (${review.failed_rules.map((rule) => rfpComplianceRuleLabels[rule] ?? rule).join("; ") || "ver detalle"})`
            : "superada"}
          .
        </li>
        <li>
          {remaining > 0
            ? `Quedan ${remaining} ${remaining === 1 ? "petición" : "peticiones"} de cambios antes del límite.`
            : "Límite de revisiones alcanzado: solo se puede aprobar o rechazar."}
        </li>
        {review.arbitration_notes.map((note) => (
          <li key={note}>Arbitraje: {note}</li>
        ))}
      </ul>
      <fieldset className="mt-3">
        <legend className="sr-only">Decisión</legend>
        <div className="flex flex-wrap gap-4">
          {review.allowed_decisions.map((option) => (
            <label key={option} className="flex items-center gap-2 text-sm text-slate-900">
              <input
                type="radio"
                name={`${formId}-decision`}
                value={option}
                checked={decision === option}
                onChange={() => setDecision(option)}
              />
              {rfpDecisionLabels[option]}
            </label>
          ))}
        </div>
      </fieldset>
      <label htmlFor={`${formId}-comment`} className="mt-3 block text-xs font-semibold uppercase tracking-wide text-slate-600">
        {decision === "approve" ? "Comentario (opcional)" : "Motivo (obligatorio)"}
      </label>
      <textarea
        id={`${formId}-comment`}
        value={comment}
        onChange={(event) => setComment(event.target.value)}
        rows={3}
        maxLength={2000}
        className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2 text-sm text-slate-900"
      />
      {departmentId === "warehouse" && decision === "approve" ? (
        <>
          <label htmlFor={`${formId}-capacity`} className="mt-3 block text-xs font-semibold uppercase tracking-wide text-slate-600">
            Capacidad comprometida (pedidos/mes, opcional)
          </label>
          <input
            id={`${formId}-capacity`}
            type="number"
            min={1}
            step={1}
            value={capacity}
            onChange={(event) => setCapacity(event.target.value)}
            className="mt-1 w-48 rounded-md border border-slate-300 bg-white p-2 text-sm text-slate-900"
          />
        </>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={sending}
        className="mt-3 rounded-md bg-cyan-700 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-800 disabled:opacity-60"
      >
        {sending ? "Enviando…" : `Registrar: ${rfpDecisionLabels[decision]}`}
      </button>
    </form>
  );
}
