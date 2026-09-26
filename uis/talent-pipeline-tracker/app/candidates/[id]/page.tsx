"use client";

import { useParams } from "next/navigation";
import CandidateDetailClient from "@/components/CandidateDetailClient";

export default function CandidateDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;

  if (!id) {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-6">
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          No se encontro el identificador de la candidatura.
        </p>
      </main>
    );
  }

  return <CandidateDetailClient id={id} />;
}
