import fs from "node:fs";
import path from "node:path";
import { parseEnv } from "node:util";
import type { NextConfig } from "next";

// Raíz del monorepo: el backoffice importa la lógica de negocio del Hito 2
// desde `<repo>/src` (alias `@trackflow/logic/*` en tsconfig.json) sin copiarla.
// Turbopack no resuelve archivos fuera de su `root`, por eso se amplía.
const monorepoRoot = path.join(__dirname, "..", "..");

// La telemetría se configura en el `.env` de la raíz, junto a la de la API.
// Next solo lee los `.env` de esta carpeta, así que se copian aquí las
// `NEXT_PUBLIC_TELEMETRY_*` antes de compilar (Next las inserta en el bundle).
// Solo esas: el resto del `.env` raíz trae URLs de Docker (`http://api:8000`)
// que romperían los rewrites en local. Una variable ya definida en el entorno
// (p. ej. por Docker Compose) tiene prioridad.
function loadRootTelemetryEnv(): void {
  const envFile = path.join(monorepoRoot, ".env");
  if (!fs.existsSync(envFile)) return;
  const values = parseEnv(fs.readFileSync(envFile, "utf8"));
  for (const [key, value] of Object.entries(values)) {
    if (key.startsWith("NEXT_PUBLIC_TELEMETRY_") && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

loadRootTelemetryEnv();
const apiOrigin = (
  process.env.TRACKFLOW_API_INTERNAL_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");
const incidentsApiOrigin = (
  process.env.INCIDENTS_API_INTERNAL_URL ?? apiOrigin
).replace(/\/$/, "");
const suppliersApiOrigin = (
  process.env.SUPPLIERS_API_INTERNAL_URL ?? incidentsApiOrigin
).replace(/\/$/, "");
// El navegador llama a `/api/inventory/*` y Next lo reenvía a la API, así que
// el puerto de la API no tiene que ser accesible desde el navegador.
const inventoryApiOrigin = (
  process.env.NEXT_PUBLIC_INVENTORY_API_URL ?? apiOrigin
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  turbopack: {
    root: monorepoRoot,
  },
  outputFileTracingRoot: monorepoRoot,
  async rewrites() {
    return [
      {
        source: "/api/incidents",
        destination: `${incidentsApiOrigin}/api/incidents`,
      },
      {
        source: "/api/incidents/:path*",
        destination: `${incidentsApiOrigin}/api/incidents/:path*`,
      },
      {
        source: "/api/suppliers/:path*",
        destination: `${suppliersApiOrigin}/suppliers/:path*`,
      },
      {
        source: "/api/inventory/:path*",
        destination: `${inventoryApiOrigin}/inventory/:path*`,
      },
      {
        // Ingesta de telemetría cuando NEXT_PUBLIC_TELEMETRY_ENDPOINT es
        // `/api/telemetry/events` (Docker, Codespaces: la API no es accesible
        // desde el navegador).
        source: "/api/telemetry/:path*",
        destination: `${apiOrigin}/telemetry/:path*`,
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
