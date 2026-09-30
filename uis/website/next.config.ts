import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // La app es independiente dentro del monorepo: fija su raíz para que
  // Turbopack no tome el package-lock.json de la raíz del repo.
  turbopack: {
    root: path.join(__dirname),
  },
  // CSS de Tailwind (~6 KB) en <style> en lugar de <link>: sin la petición bloqueante,
  // FCP/LCP móvil con throttling real 1,7 s → 1,0 s. Coste: HTML ~19 KB mayor y sin
  // caché del CSS para visitas recurrentes (ver audit/AUDIT.md, P3).
  experimental: {
    inlineCss: true,
  },
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "images.unsplash.com",
        pathname: "/**",
      },
    ],
  },
};

export default nextConfig;
