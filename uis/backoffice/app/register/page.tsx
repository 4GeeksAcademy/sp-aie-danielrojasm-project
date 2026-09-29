import type { Metadata } from "next";
import { AuthScreen } from "@/components/auth/AuthScreen";
import { RegisterForm } from "@/components/auth/RegisterForm";

export const metadata: Metadata = { title: "Crear cuenta" };

export default function RegisterPage() {
  return (
    <AuthScreen
      title="Crear cuenta"
      description="Registra tus credenciales y, si lo necesitas, completa ahora tus datos de contacto."
      alternateText="¿Ya tienes una cuenta?"
      alternateLabel="Iniciar sesión"
      alternateHref="/login"
    >
      <RegisterForm />
    </AuthScreen>
  );
}