// Mide los layout shifts reales de vistas del backoffice con sesión (PerformanceObserver
// de `layout-shift`, CPU 4×) y muestra qué nodo se movió y cuánto. Complementa a
// lighthouse-runner.mjs cuando hay que ver el CLS a varios anchos (ver AUDIT.md, P2 y P7).
// Uso: W=412 AUDIT_EMAIL=... AUDIT_PASSWORD=... node layout-shift-probe.mjs /suppliers,/inventory/products
// ALL=1 muestra todas las fuentes de cada shift.
import fs from "node:fs"; import path from "node:path"; import puppeteer from "puppeteer-core";
const chrome = fs.readdirSync(path.join(process.env.HOME, ".cache/ms-playwright")).filter((d) => d.startsWith("chromium-")).map((d) => path.join(process.env.HOME, ".cache/ms-playwright", d, "chrome-linux64/chrome"))[0];
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password } = process.env;
if (!email || !password) throw new Error("Faltan AUDIT_EMAIL y AUDIT_PASSWORD");
const { access_token } = await (await fetch("http://localhost:8000/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) })).json();
const b = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox"] });
const p = await b.newPage();
await p.emulate({ viewport: { width: Number(process.env.W ?? 412), height: 823, deviceScaleFactor: 1, isMobile: Number(process.env.W ?? 412) < 640, hasTouch: false }, userAgent: "Mozilla/5.0 (Linux; Android 11) Mobile" });
await p.goto("http://localhost:3002/login", { waitUntil: "networkidle0" });
await p.evaluate((t) => localStorage.setItem("trackflow_access_token", t), access_token);
await p.evaluateOnNewDocument(() => {
  window.__shifts = [];
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) {
      window.__shifts.push({ t: Math.round(e.startTime), v: e.value.toFixed(4), src: e.sources.map((s) => {
        const n = s.node; const d = n && n.nodeType === 1 ? `${n.tagName}.${(n.className || "").toString().slice(0, 40)} "${(n.innerText || "").slice(0, 40)}"` : n ? `#text "${n.textContent.slice(0, 30)}"` : "?";
        return `${d} ${Math.round(s.previousRect.y)}→${Math.round(s.currentRect.y)} h ${Math.round(s.previousRect.height)}→${Math.round(s.currentRect.height)}`;
      }) });
    }
  }).observe({ type: "layout-shift", buffered: true });
});
const cdp = await p.createCDPSession(); await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
for (const url of (process.argv[2] ?? "/inventory/products").split(",")) {
  await p.goto("http://localhost:3002" + url, { waitUntil: "networkidle0" });
  await new Promise((r) => setTimeout(r, 1500));
  const shifts = await p.evaluate(() => window.__shifts);
  const total = shifts.reduce((sum, s) => sum + Number(s.v), 0).toFixed(4);
  console.log(url, "CLS≈", total, JSON.stringify(process.env.ALL ? shifts : shifts.map((s) => s.src[0]), null, process.env.ALL ? 1 : 0));
}
await b.close();
