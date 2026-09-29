import path from "node:path";
import type { NextConfig } from "next";

// Raíz del monorepo: el backoffice importa la lógica de negocio del Hito 2
// desde `<repo>/src` (alias `@trackflow/logic/*` en tsconfig.json) sin copiarla.
// Turbopack no resuelve archivos fuera de su `root`, por eso se amplía.
const monorepoRoot = path.join(__dirname, "..", "..");

const nextConfig: NextConfig = {
  turbopack: {
    root: monorepoRoot,
  },
  outputFileTracingRoot: monorepoRoot,
};

export default nextConfig;
