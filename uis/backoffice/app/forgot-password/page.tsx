import type { Metadata } from "next";
import { AuthScreen } from "@/components/auth/AuthScreen";
import { ForgotPasswordForm } from "@/components/auth/ForgotPasswordForm";

export const metadata: Metadata = { title: "Recuperar contraseña" };

export default function ForgotPasswordPage() {
  return <AuthScreen title="Recuperar contraseña" description="Recibe un enlace para establecer una nueva contraseña." alternateText="¿Recuerdas tu contraseña?" alternateLabel="Iniciar sesión" alternateHref="/login"><ForgotPasswordForm /></AuthScreen>;
}