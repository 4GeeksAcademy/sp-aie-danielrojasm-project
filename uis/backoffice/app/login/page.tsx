import type { Metadata } from "next";
import { AuthScreen } from "@/components/auth/AuthScreen";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata: Metadata = { title: "Iniciar sesión" };

export default function LoginPage() {
  return (
    <AuthScreen
      title="Iniciar sesión"
      description="Accede al entorno interno de operaciones de TrackFlow."
      alternateText="¿Todavía no tienes cuenta?"
      alternateLabel="Crear una cuenta"
      alternateHref="/register"
    >
      <LoginForm />
    </AuthScreen>
  );
}