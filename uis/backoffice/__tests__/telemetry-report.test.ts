/** Reporte técnico de telemetría: utilidades de `lib/telemetry-report.ts`. */
import { formatRate, formatUtc, rateVital, reportQuery } from "@/lib/telemetry-report";

describe("reportQuery", () => {
  it("sin días usa la ventana por defecto de la API", () => {
    expect(reportQuery({ from: "", to: "" })).toBe("");
  });

  it("incluye el día final entero porque end_date es exclusivo", () => {
    expect(reportQuery({ from: "2026-09-01", to: "2026-09-30" })).toBe(
      "?start_date=2026-09-01T00%3A00%3A00Z&end_date=2026-10-01T00%3A00%3A00Z",
    );
  });

  it("acepta un solo extremo", () => {
    expect(reportQuery({ from: "", to: "2026-12-31" })).toBe("?end_date=2027-01-01T00%3A00%3A00Z");
  });
});

describe("rateVital", () => {
  it("aplica los umbrales de Web Vitals con los límites incluidos", () => {
    expect(rateVital("lcp_ms_p75", 2500)).toBe("good");
    expect(rateVital("lcp_ms_p75", 2501)).toBe("needs_improvement");
    expect(rateVital("lcp_ms_p75", 4001)).toBe("poor");
    expect(rateVital("cls_p75", 0.1)).toBe("good");
    expect(rateVital("inp_ms_p75", 600)).toBe("poor");
  });
});

describe("formatos", () => {
  it("muestra las tasas en porcentaje y las fechas en UTC", () => {
    expect(formatRate(0.6667)).toBe("66,7 %");
    expect(formatUtc("2026-10-01T17:02:31Z")).toMatch(/UTC$/);
  });
});
