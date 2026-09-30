// JS inicial de cada ruta del backoffice tras `npm run build`.
//
// Uso, desde uis/backoffice:  node ../../audit/caching/route-js.mjs [--json salida.json]
//
// Lee el HTML prerenderizado de cada ruta (.next/server/app/<ruta>.html), suma
// los <script src> que el navegador descarga al cargarla y los compara con el
// total de chunks del build. Un componente cargado con next/dynamic sale de
// esa lista y solo se pide cuando se renderiza.
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const NEXT_DIR = ".next";
const ROUTES = { "/": "index", "/incidents/analyzer": "incidents/analyzer", "/incidents": "incidents" };

function sizes(file) {
  const content = readFileSync(join(NEXT_DIR, "static", "chunks", file));
  return { raw: content.length, gzip: gzipSync(content).length };
}

function initialChunks(htmlFile) {
  const html = readFileSync(htmlFile, "utf8");
  const files = new Set();
  for (const match of html.matchAll(/\/_next\/static\/chunks\/([^"'?\s]+\.js)/g)) files.add(match[1]);
  return [...files];
}

const result = {};
for (const [route, name] of Object.entries(ROUTES)) {
  const htmlFile = join(NEXT_DIR, "server", "app", `${name}.html`);
  if (!existsSync(htmlFile)) throw new Error(`No existe ${htmlFile}: ejecuta npm run build.`);
  const chunks = initialChunks(htmlFile);
  const total = chunks.map(sizes).reduce((acc, s) => ({ raw: acc.raw + s.raw, gzip: acc.gzip + s.gzip }), { raw: 0, gzip: 0 });
  result[route] = { chunks: chunks.length, rawKB: +(total.raw / 1024).toFixed(1), gzipKB: +(total.gzip / 1024).toFixed(1) };
}

const allChunks = readdirSync(join(NEXT_DIR, "static", "chunks")).filter((file) => file.endsWith(".js"));
result.buildChunks = allChunks.length;

console.table(result);
const jsonIndex = process.argv.indexOf("--json");
if (jsonIndex > -1) writeFileSync(process.argv[jsonIndex + 1], `${JSON.stringify(result, null, 2)}\n`);
