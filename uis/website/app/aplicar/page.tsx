import type { Metadata } from "next";
import { ApplicationForm } from "@/components/forms/ApplicationForm";

export const metadata: Metadata = {
  title: "Formulario de aplicación",
  description:
    "Formulario de aplicación para empresas interesadas en modernizar su logística con TrackFlow.",
};

export default function ApplicationPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      <section className="mb-8" aria-labelledby="form-title">
        <h1
          id="form-title"
          className="text-3xl font-black text-white sm:text-4xl"
        >
          Formulario de aplicación y registro
        </h1>
        <p className="mt-3 max-w-3xl text-slate-300">
          Comparte los datos de tu empresa y de tu operación logística para
          preparar una propuesta de implementación adaptada a tus objetivos.
        </p>
      </section>
      <ApplicationForm />
    </div>
  );
}
