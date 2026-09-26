import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { company } from "@/content/site";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL(company.url),
  title: {
    default: "TrackFlow | Logística inteligente de última milla",
    template: "%s | TrackFlow",
  },
  description:
    "TrackFlow moderniza la logística de última milla y almacenes en Estados Unidos y España con operaciones 24/7, visibilidad en tiempo real y experiencia de cliente de alto nivel.",
  keywords: [
    "logística",
    "última milla",
    "almacenes",
    "tracking",
    "devoluciones",
    "fulfillment",
    "TrackFlow",
  ],
  robots: { index: true, follow: true },
  openGraph: {
    title: "TrackFlow | Logística inteligente",
    description:
      "Gestión integral de inventario, envíos y devoluciones para marcas de e-commerce en Estados Unidos y España.",
    type: "website",
    url: company.url,
    images: [
      "https://images.unsplash.com/photo-1553413077-190dd305871c?auto=format&fit=crop&w=1200&q=80",
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className={`${geistSans.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-slate-950 text-slate-100">
        <SiteHeader />
        <main id="inicio" className="flex-1">
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
