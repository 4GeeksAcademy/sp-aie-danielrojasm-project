/** Tests unitarios de la lógica de `lib/` (sin renderizar componentes). */
/** @type {import('jest').Config} */
module.exports = {
  testEnvironment: "node",
  roots: ["<rootDir>/__tests__"],
  transform: {
    // Next usa `module: esnext` + `moduleResolution: bundler`; Jest necesita CommonJS.
    "^.+\\.tsx?$": [
      "ts-jest",
      { tsconfig: { module: "commonjs", moduleResolution: "node", jsx: "react-jsx" } },
    ],
  },
  moduleNameMapper: { "^@/(.*)$": "<rootDir>/$1" },
  collectCoverageFrom: [
    "lib/api-client.ts",
    "lib/incidents.ts",
    "lib/labels.ts",
    "lib/registration.ts",
  ],
};
