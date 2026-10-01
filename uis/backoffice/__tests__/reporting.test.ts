/** Reporte semanal de desempeño: utilidades de `lib/reporting.ts`. */
import {
  clientName,
  formatKpi,
  formatWeekRange,
  shiftWeek,
  weeklyTotals,
  type WeeklyPerformanceEntry,
} from "@/lib/reporting";

const entry = (overrides: Partial<WeeklyPerformanceEntry>): WeeklyPerformanceEntry => ({
  warehouse: "zaragoza",
  client_id: "purestep-footwear",
  inbound_units_count: 0,
  outbound_orders_count: 0,
  stockout_events_count: 0,
  discrepancy_events_count: 0,
  discrepancy_rate: 0,
  ...overrides,
});

describe("weeklyTotals", () => {
  it("suma los conteos y recalcula la tasa sobre los totales, no como media de tasas", () => {
    const totals = weeklyTotals([
      entry({ inbound_units_count: 40, outbound_orders_count: 1, discrepancy_events_count: 1, discrepancy_rate: 1 }),
      entry({ warehouse: "los_angeles", inbound_units_count: 25, outbound_orders_count: 9, stockout_events_count: 2 }),
    ]);
    expect(totals).toEqual({
      inbound_volume: 65,
      outbound_throughput: 10,
      stockout_frequency: 2,
      discrepancy_rate: 0.1,
    });
  });

  it("la tasa es 0 sin pedidos despachados", () => {
    expect(weeklyTotals([entry({ discrepancy_events_count: 3 })]).discrepancy_rate).toBe(0);
    expect(weeklyTotals([]).discrepancy_rate).toBe(0);
  });
});

describe("formatos", () => {
  it("muestra los conteos en es-ES y la tasa en porcentaje", () => {
    expect(formatKpi("inbound_volume", 4200)).toBe("4.200");
    expect(formatKpi("inbound_volume", 42000)).toBe("42.000");
    expect(formatKpi("discrepancy_rate", 0.25)).toBe("25 %");
    expect(formatKpi("discrepancy_rate", 0.0021)).toBe("0,2 %");
  });

  it("hace legible el identificador del cliente", () => {
    expect(clientName("purestep-footwear")).toBe("Purestep Footwear");
    expect(clientName("fashion-co")).toBe("Fashion Co");
  });
});

describe("semanas", () => {
  it("se desplaza de lunes a lunes", () => {
    expect(shiftWeek("2026-09-21", -1)).toBe("2026-09-14");
    expect(shiftWeek("2026-12-28", 1)).toBe("2027-01-04");
  });

  it("describe el período de lunes a domingo", () => {
    expect(formatWeekRange("2026-09-21")).toBe("del 21 al 27 de septiembre de 2026");
    expect(formatWeekRange("2026-09-28")).toBe("del 28 de septiembre al 4 de octubre de 2026");
    expect(formatWeekRange("2026-12-28")).toBe("del 28 de diciembre de 2026 al 3 de enero de 2027");
  });
});
