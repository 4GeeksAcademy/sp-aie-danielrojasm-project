import path from "node:path";
import type { NextConfig } from "next";

// Raíz del monorepo: el backoffice importa la lógica de negocio del Hito 2
// desde `<repo>/src` (alias `@trackflow/logic/*` en tsconfig.json) sin copiarla.
// Turbopack no resuelve archivos fuera de su `root`, por eso se amplía.
const monorepoRoot = path.join(__dirname, "..", "..");
const apiOrigin = (
  process.env.TRACKFLOW_API_INTERNAL_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");
const incidentsApiOrigin = (
  process.env.INCIDENTS_API_INTERNAL_URL ?? apiOrigin
).replace(/\/$/, "");
const suppliersApiOrigin = (
  process.env.SUPPLIERS_API_INTERNAL_URL ?? incidentsApiOrigin
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  turbopack: {
    root: monorepoRoot,
  },
  outputFileTracingRoot: monorepoRoot,
  async rewrites() {
    return [
      {
        source: "/api/incidents/:path*",
        destination: `${incidentsApiOrigin}/api/incidents/:path*`,
      },
      {
        source: "/api/suppliers/:path*",
        destination: `${suppliersApiOrigin}/suppliers/:path*`,
      },
      {
        source: "/api/auth/:path*",
        destination: `${apiOrigin}/auth/:path*`,
      },
      {
        source: "/api/users/:path*",
        destination: `${apiOrigin}/users/:path*`,
      },
      {
        source: "/api/users",
        destination: `${apiOrigin}/users`,
      },
      {
        source: "/api/profiles/:path*",
        destination: `${apiOrigin}/profiles/:path*`,
      },
    ];
  },
};

export default nextConfig;
