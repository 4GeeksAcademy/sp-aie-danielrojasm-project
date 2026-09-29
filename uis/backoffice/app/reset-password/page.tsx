import type { Metadata } from "next";
import { AuthScreen } from "@/components/auth/AuthScreen";
import { ResetPasswordForm } from "@/components/auth/ResetPasswordForm";

export const metadata: Metadata = { title: "Restablecer contraseña" };

export default async function ResetPasswordPage({ searchParams }: { searchParams: Promise<{ token?: string | string[] }> }) {
  const { token } = await searchParams;
  return <AuthScreen title="Nueva contraseña" description="Establece la contraseña con la que accederás a tu cuenta." alternateText="¿Necesitas otro enlace?" alternateLabel="Solicitar enlace" alternateHref="/forgot-password"><ResetPasswordForm token={typeof token === "string" ? token : undefined} /></AuthScreen>;
}