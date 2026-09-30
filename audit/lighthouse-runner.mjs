// Lighthouse reproducible para la auditoría de rendimiento (ver AUDIT.md).
// 3 corridas por URL y modo (mobile/desktop); se guarda la mediana como JSON y una
// captura PNG de la cabecera del informe (puntuaciones + métricas). No se escribe HTML.
// Requiere website (:3000), backoffice (:3002) y API (:8000) en modo producción,
// `npm i lighthouse@12 puppeteer-core` en una carpeta aparte y Chromium de Playwright.
// Uso: AUDIT_EMAIL=... AUDIT_PASSWORD=... node lighthouse-runner.mjs <outDir> [filtro]
import fs from "node:fs";
import path from "node:path";
import lighthouse from "lighthouse";
import desktopConfig from "lighthouse/core/config/desktop-config.js";
import { computeMedianRun } from "lighthouse/core/lib/median-run.js";
import { ReportGenerator } from "lighthouse/report/generator/report-generator.js";
import puppeteer from "puppeteer-core";

const RUNS = 3;
const CHROME = fs
  .readdirSync(path.join(process.env.HOME, ".cache/ms-playwright"))
  .filter((d) => d.startsWith("chromium-"))
  .map((d) => path.join(process.env.HOME, ".cache/ms-playwright", d, "chrome-linux64/chrome"))[0];

const outDir = process.argv[2];
const filter = process.argv[3] ?? "";
fs.mkdirSync(outDir, { recursive: true });

const pages = [
  { name: "website-home", url: "http://localhost:3000/" },
  { name: "website-aplicar", url: "http://localhost:3000/aplicar" },
  { name: "backoffice-dashboard", url: "http://localhost:3002/", auth: true },
  { name: "backoffice-inventory", url: "http://localhost:3002/inventory/products", auth: true },
];

async function token() {
  const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password } = process.env;
  if (!email || !password) throw new Error("Faltan AUDIT_EMAIL y AUDIT_PASSWORD");
  const res = await fetch("http://localhost:8000/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(`login ${res.status}`);
  return (await res.json()).access_token;
}

async function runOnce(pageDef, mode) {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ["--no-sandbox", "--disable-gpu", "--disable-extensions"],
  });
  try {
    const page = await browser.newPage();
    const flags = { output: "json", logLevel: "error" };
    if (pageDef.auth) {
      // Sesión real: JWT en localStorage como hace el login del backoffice.
      await page.goto(new URL("/login", pageDef.url).href, { waitUntil: "networkidle0" });
      const jwt = await token();
      await page.evaluate((t) => localStorage.setItem("trackflow_access_token", t), jwt);
      await page.goto("about:blank");
      flags.disableStorageReset = true;
    }
    const config = mode === "desktop" ? desktopConfig : undefined;
    return await lighthouse(pageDef.url, flags, config, page);
  } finally {
    await browser.close();
  }
}

/** Renderiza el informe en memoria y captura su cabecera. */
async function screenshot(lhr, file) {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1100, height: 1500, deviceScaleFactor: 1 });
    await page.setContent(ReportGenerator.generateReportHtml(lhr), { waitUntil: "networkidle0" });
    // Sin animaciones; el número del gauge grande se pinta duplicado en headless y ya
    // aparece en la fila superior de puntuaciones.
    await page.addStyleTag({
      content:
        "*, *::before, *::after { transition: none !important; animation: none !important; } .lh-exp-gauge__percentage { display: none; }",
    });
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await page.screenshot({ path: file });
  } finally {
    await browser.close();
  }
}

for (const pageDef of pages) {
  for (const mode of ["mobile", "desktop"]) {
    const id = `${pageDef.name}-${mode}`;
    if (filter && !id.includes(filter)) continue;
    const results = [];
    for (let i = 0; i < RUNS; i++) results.push(await runOnce(pageDef, mode));
    const median = computeMedianRun(results.map((r) => r.lhr));
    const chosen = results.find((r) => r.lhr === median);
    fs.writeFileSync(path.join(outDir, `${id}.json`), chosen.report);
    await screenshot(median, path.join(outDir, `${id}.png`));
    const s = Object.fromEntries(
      Object.entries(median.categories).map(([k, v]) => [k, Math.round(v.score * 100)]),
    );
    const perfRuns = results.map((r) => Math.round(r.lhr.categories.performance.score * 100));
    console.log(id, JSON.stringify(s), "perf runs", perfRuns.join("/"), "final", median.finalDisplayedUrl);
  }
}
