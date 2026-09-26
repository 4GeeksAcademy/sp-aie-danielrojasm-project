import CandidatesListClient from "@/components/CandidatesListClient";
import { Suspense } from "react";

export default function HomePage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto w-full max-w-6xl px-4 py-6 md:px-6">
          <p className="rounded-lg border border-cyan-300/30 bg-cyan-300/10 px-3 py-2 text-sm text-cyan-100">
            Cargando candidaturas...
          </p>
        </main>
      }
    >
      <CandidatesListClient />
    </Suspense>
  );
}
