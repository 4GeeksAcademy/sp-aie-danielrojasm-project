import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // La app es independiente dentro del monorepo: fija su raíz para que
  // Turbopack no tome el package-lock.json de la raíz del repo.
  turbopack: {
    root: path.join(__dirname),
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
