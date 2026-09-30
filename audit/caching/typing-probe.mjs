// Coste por pulsación en los formularios de movimientos de inventario.
//
// Uso (backoffice con `next start` y la API con el volumen de seed_load_test.py):
//   PUPPETEER_CORE=<ruta a node_modules/puppeteer-core> CHROME=<chrome.exe> \
//   BACKOFFICE=http://localhost:3102 API=http://127.0.0.1:8011 \
//   AUDIT_EMAIL=... AUDIT_PASSWORD=... node audit/caching/typing-probe.mjs <label>
//
// Abre /inventory/orders/outbound, espera a que el selector tenga todo el
// catálogo de SKUs y escribe 40 caracteres en el campo de número de
// seguimiento con la CPU a 4×. Cada pulsación re-renderiza el formulario; se
// mide, por pulsación, el tiempo entre el listener de captura del evento
// `input` en window y el final de sus microtareas: el onChange, el render y el
// commit de React. (La Event Timing API no sirve aquí: no reporta eventos de
// menos de 16 ms.) Se repite `RUNS` veces y se da la mediana de las corridas.
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const puppeteerPath = process.env.PUPPETEER_CORE;
const { default: puppeteer } = await import(puppeteerPath ? pathToFileURL(`${puppeteerPath}/lib/esm/puppeteer/puppeteer-core.js`).href : "puppeteer-core");
const { CHROME, BACKOFFICE = "http://localhost:3102", API = "http://127.0.0.1:8011", AUDIT_EMAIL: email, AUDIT_PASSWORD: password } = process.env;
const label = process.argv[2] ?? "probe";
const RUNS = Number(process.env.RUNS ?? 5);
const TEXT = "1Z999AA10123456784JJD0003900077755120000";

const login = await fetch(`${API}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
const { access_token } = await login.json();
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
await page.goto(`${BACKOFFICE}/login`, { waitUntil: "networkidle0" });
await page.evaluate((token) => localStorage.setItem("trackflow_access_token", token), access_token);
const cdp = await page.createCDPSession();

const median = (values) => { const s = [...values].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : 0; };
const p95 = (values) => { const s = [...values].sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.round(0.95 * (s.length - 1)))] : 0; };
const runs = [];

for (let run = 0; run < RUNS; run += 1) {
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
  await page.goto(`${BACKOFFICE}/inventory/orders/outbound`, { waitUntil: "networkidle0" });
  await page.waitForFunction(() => document.querySelectorAll("select option").length > 1000, { timeout: 60000 });
  const options = await page.evaluate(() => document.querySelectorAll("select option").length);
  await page.evaluate(() => {
    // React procesa el `input` (onChange + render + commit) de forma síncrona en
    // su listener de la raíz: queda entre la captura y la burbuja en window.
    window.__keys = [];
    let start = 0;
    window.addEventListener("input", () => { start = performance.now(); }, true);
    window.addEventListener("input", () => {
      const syncEnd = performance.now();
      queueMicrotask(() => window.__keys.push({ sync: syncEnd - start, withMicrotasks: performance.now() - start }));
    });
  });
  const input = await page.waitForSelector("#exit-tracking");
  await input.click();
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  for (const char of TEXT) {
    await page.keyboard.type(char);
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0))));
  }
  await new Promise((resolve) => setTimeout(resolve, 500));
  const keys = await page.evaluate(() => window.__keys);
  const perKey = keys.map((entry) => entry.withMicrotasks);
  runs.push({ options, keys: perKey.length, medianMs: +median(perKey).toFixed(2), p95Ms: +p95(perKey).toFixed(2), maxMs: +Math.max(...perKey).toFixed(2), value: await page.$eval("#exit-tracking", (el) => el.value.length).catch(() => null) });
}
await browser.close();

const summary = {
  label,
  cpuThrottling: 4,
  keystrokes: TEXT.length,
  runs,
  medianMs: median(runs.map((run) => run.medianMs)),
  p95Ms: median(runs.map((run) => run.p95Ms)),
};
console.log(JSON.stringify(summary, null, 2));
writeFileSync(new URL(`./results/typing-${label}.json`, import.meta.url), `${JSON.stringify(summary, null, 2)}\n`);
