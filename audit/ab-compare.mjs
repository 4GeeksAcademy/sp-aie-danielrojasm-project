// A/B/C intercalado del website: misma máquina y mismas condiciones, N rondas alternando
// variantes para que la carga del host afecte a todas por igual (ver REPORT.md).
// Cada variante es un build de producción servido en su puerto, p. ej. un `git worktree`
// del commit original en :3100, el commit sin inlineCss en :3200 y HEAD en :3000.
// Uso: ROUNDS=5 THROTTLING=simulate|devtools node ab-compare.mjs  → ab-<throttling>.json
import fs from "node:fs"; import path from "node:path";
import lighthouse from "lighthouse"; import puppeteer from "puppeteer-core";
const CHROME = fs.readdirSync(path.join(process.env.HOME, ".cache/ms-playwright")).filter((d) => d.startsWith("chromium-")).map((d) => path.join(process.env.HOME, ".cache/ms-playwright", d, "chrome-linux64/chrome"))[0];
const variants = { original: 3100, "sin-inline": 3200, actual: 3000 };
const pagesToRun = ["/", "/aplicar"]; const ROUNDS = Number(process.env.ROUNDS ?? 5);
const throttlingMethod = process.env.THROTTLING ?? "simulate";
const rows = [];
for (let round = 0; round < ROUNDS; round++) for (const pg of pagesToRun) for (const [name, port] of Object.entries(variants)) {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox", "--disable-gpu"] });
  const page = await browser.newPage();
  const { lhr } = await lighthouse(`http://localhost:${port}${pg}`, { output: "json", logLevel: "error", throttlingMethod, onlyCategories: ["performance"] }, undefined, page);
  await browser.close();
  const a = lhr.audits;
  rows.push({ round, pg, name, perf: Math.round(lhr.categories.performance.score * 100), fcp: a["first-contentful-paint"].numericValue, lcp: a["largest-contentful-paint"].numericValue, tbt: a["total-blocking-time"].numericValue });
  process.stdout.write(".");
}
fs.writeFileSync(`ab-${throttlingMethod}.json`, JSON.stringify(rows, null, 1));
const med = (xs) => { const s = [...xs].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
console.log(`\n${throttlingMethod}, ${ROUNDS} rondas, mediana [min–max]`);
for (const pg of pagesToRun) for (const name of Object.keys(variants)) {
  const r = rows.filter((x) => x.pg === pg && x.name === name);
  const f = (k, u = "") => `${Math.round(med(r.map((x) => x[k])))}${u} [${Math.round(Math.min(...r.map((x) => x[k])))}–${Math.round(Math.max(...r.map((x) => x[k])))}]`;
  console.log(`${pg.padEnd(9)} ${name.padEnd(11)} perf ${f("perf")}  FCP ${f("fcp", "ms")}  LCP ${f("lcp", "ms")}  TBT ${f("tbt", "ms")}`);
}
