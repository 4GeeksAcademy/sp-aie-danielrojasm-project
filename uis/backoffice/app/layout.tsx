import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { ProtectedShell } from "@/components/auth/ProtectedShell";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Backoffice | TrackFlow",
    template: "%s | Backoffice TrackFlow",
  },
  description:
    "Aplicación interna de TrackFlow para operaciones de almacén, transportistas y envíos.",
  robots: { index: false, follow: false },
};

/** Layout interno: navegación lateral + barra superior (independiente de uis/website). */
export default function BackofficeLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="es"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-slate-100 text-slate-900">
        <AuthProvider>
          <ProtectedShell>{children}</ProtectedShell>
        </AuthProvider>
      </body>
    </html>
  );
}
