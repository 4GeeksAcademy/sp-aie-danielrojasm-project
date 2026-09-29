import type { Metadata } from "next";
import { ChangePasswordForm } from "@/components/account/ChangePasswordForm";

export const metadata: Metadata = { title: "Cambiar contraseña" };

export default function ChangePasswordPage() {
  return <ChangePasswordForm />;
}