import type { Metadata } from "next";
import { AuthScreen } from "@/components/auth/AuthScreen";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata: Metadata = { title: "Iniciar sesión" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ reset?: string }> }) {
  const { reset } = await searchParams;
  return (
    <AuthScreen
      title="Iniciar sesión"
      description="Accede al entorno interno de operaciones de TrackFlow."
      alternateText="¿Todavía no tienes cuenta?"
      alternateLabel="Crear una cuenta"
      alternateHref="/register"
    >
      {reset === "success" ? <p role="status" className="mb-5 border-l-4 border-emerald-500 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">Contraseña restablecida. Ya puedes iniciar sesión.</p> : null}
      <LoginForm />
    </AuthScreen>
  );
}