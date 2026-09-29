/** FE-019: formateadores numéricos (`lib/labels.ts`). */
import { formatNumber, formatUSD } from "@/lib/labels";

// Intl separa importe y símbolo con un espacio duro (U+00A0).
const normalize = (text: string) => text.replace(/\s/g, " ");

describe("formatUSD", () => {
  it("usa formato español con dos decimales", () => {
    expect(normalize(formatUSD(1800))).toBe("1800,00 US$");
    expect(normalize(formatUSD(12345.6))).toBe("12.345,60 US$");
  });

  it("redondea a céntimos y respeta negativos", () => {
    expect(normalize(formatUSD(0.425))).toMatch(/^0,4[23] US\$$/);
    expect(normalize(formatUSD(-7.9))).toBe("-7,90 US$");
  });

  it("no oculta un valor no numérico", () => {
    // Un NaN que llega a la UI debe verse como tal, no como 0 $.
    expect(formatUSD(Number.NaN)).toContain("NaN");
  });
});

describe("formatNumber", () => {
  it("limita a dos decimales", () => {
    expect(formatNumber(3.14159)).toBe("3,14");
  });
});
