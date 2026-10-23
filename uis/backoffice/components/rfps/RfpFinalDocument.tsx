"use client";

import { useEffect, useState } from "react";
import { RetryAlert } from "@/components/inventory/RetryAlert";
import { Panel } from "@/components/ui/Panel";
import { getUserMessage } from "@/lib/api-client";
import { formatRfpDate, getRfpDocument, type RfpFinalDocument as FinalDocument } from "@/lib/rfps";

const LOAD_FALLBACK_ERROR = "No se pudo cargar el documento final.";

interface RfpFinalDocumentProps {
  ticketId: string;
  clientName: string | null;
}

/** Documento final consolidado con las secciones aprobadas, listo para Ventas. */
export function RfpFinalDocument({ ticketId, clientName }: RfpFinalDocumentProps) {
  const [document, setDocument] = useState<FinalDocument | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    getRfpDocument(ticketId)
      .then((loaded) => {
        if (!active) return;
        setDocument(loaded);
        setError("");
      })
      .catch((caught: unknown) => {
        if (active) setError(getUserMessage(caught, LOAD_FALLBACK_ERROR));
      });
    return () => {
      active = false;
    };
  }, [ticketId, attempt]);

  const download = () => {
    if (!document) return;
    const url = URL.createObjectURL(new Blob([document.content], { type: "text/markdown;charset=utf-8" }));
    const link = window.document.createElement("a");
    link.href = url;
    link.download = `propuesta-${slug(clientName ?? ticketId)}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Panel
      id="rfp-final-document"
      title="Documento final"
      description={
        document
          ? `Generado el ${formatRfpDate(document.generated_at)} con las secciones aprobadas · ${document.currency}`
          : "Secciones aprobadas por cada responsable, consolidadas sin reescribir."
      }
    >
      {error ? <RetryAlert message={error} onRetry={() => setAttempt((value) => value + 1)} /> : null}
      {!document && !error ? (
        <p className="text-sm text-slate-500" role="status">
          Cargando el documento final…
        </p>
      ) : null}
      {document ? (
        <>
          <ul className="mb-3 space-y-1 text-sm text-slate-700">
            {document.sections.map((section) => (
              <li key={section.department_id}>
                <span className="font-semibold">{section.department_name}</span> · aprobada por {section.approver} el{" "}
                {formatRfpDate(section.approved_at)}
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={download}
            className="rounded-md bg-cyan-700 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-800"
          >
            Descargar (.md)
          </button>
          <pre className="mt-4 max-h-[36rem] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-4 font-sans text-sm leading-relaxed text-slate-800">
            {document.content}
          </pre>
        </>
      ) : null}
    </Panel>
  );
}

function slug(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
