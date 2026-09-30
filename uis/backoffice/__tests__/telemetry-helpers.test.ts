import {
  clientId,
  clientValidationFailure,
  inventoryEntryPoint,
  inventoryIdentity,
  rememberSidebarNavigation,
} from "@/lib/inventory-telemetry";
import type { SKUListItem } from "@/lib/inventory";
import {
  createWindowThrottle,
  errorFingerprint,
  firstStackFrame,
  isTokenExpired,
  routeTemplate,
  sectionForRoute,
} from "@/lib/telemetry-helpers";

const sku: SKUListItem = {
  id: 6,
  name: "Cargador USB-C 65W",
  sku: "TEC-CHG-065",
  client_name: "SoundWave Electrónica",
  category: "electronics",
  warehouse: "ZGZ",
  current_stock: 40,
};

describe("routeTemplate", () => {
  it.each([
    ["/inventory/products", "/inventory/products"],
    ["/api/inventory/products/12?warehouse=LA#x", "/api/inventory/products/{id}"],
    ["http://localhost:3002/api/incidents/7/status", "/api/incidents/{id}/status"],
    ["/api/users/4b3f1c2d-9e8a-4d7c-b6a5-1f2e3d4c5b6a", "/api/users/{id}"],
    ["/inventory/products/", "/inventory/products"],
    ["/reset-password?token=eyJhbGciOi", "/reset-password"],
    ["/buscar/ana%40example.com", "/buscar/{id}"],
  ])("%s → %s (sin ids, query ni datos)", (url, template) => {
    expect(routeTemplate(url)).toBe(template);
  });
});

describe("sectionForRoute", () => {
  it.each([
    ["/", "dashboard"],
    ["/inventory/orders/outbound", "inventory"],
    ["/incidents/analyzer", "incidents"],
    ["/suppliers", "suppliers"],
    ["/account/profile", "account"],
    ["/login", "auth"],
    ["/reset-password", "auth"],
    ["/no-existe", null],
    ["/inventoryx", null],
  ])("%s → %s", (route, section) => {
    expect(sectionForRoute(route)).toBe(section);
  });
});

describe("errorFingerprint", () => {
  const stack = [
    "TypeError: Cannot read properties of undefined (reading 'sku')",
    "    at StockExitForm (http://localhost:3002/_next/static/chunks/app.js?v=17:120:15)",
    "    at renderWithHooks (http://localhost:3002/_next/static/chunks/react.js:10:1)",
  ].join("\n");

  it("usa el primer marco del stack sin origen ni query", () => {
    expect(firstStackFrame(stack)).toBe("/_next/static/chunks/app.js:120");
    expect(firstStackFrame("foo@http://localhost:3002/app.js:9:3")).toBe("/app.js:9");
    expect(firstStackFrame(undefined)).toBe("unknown");
  });

  it("agrupa por nombre y marco, nunca por el mensaje", () => {
    const fingerprint = errorFingerprint("TypeError", stack);
    expect(fingerprint).toMatch(/^[0-9a-f]{16}$/);
    const otherMessage = stack.replace("reading 'sku'", "reading 'name'");
    expect(errorFingerprint("TypeError", otherMessage)).toBe(fingerprint);
    expect(errorFingerprint("RangeError", stack)).not.toBe(fingerprint);
  });
});

describe("isTokenExpired", () => {
  const token = (payload: object) =>
    `h.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.s`;

  it("distingue un token caducado de uno rechazado por otro motivo", () => {
    const now = Date.parse("2025-01-15T10:00:00Z");
    expect(isTokenExpired(token({ exp: now / 1000 - 1 }), now)).toBe(true);
    expect(isTokenExpired(token({ exp: now / 1000 + 60 }), now)).toBe(false);
    expect(isTokenExpired("no-es-un-jwt", now)).toBe(false);
  });
});

describe("createWindowThrottle", () => {
  it("uno por clave y ventana; las repeticiones viajan en suppressed", () => {
    let now = 0;
    const throttle = createWindowThrottle(30_000, Infinity, () => now);
    expect(throttle("/api/inventory/products|503")).toEqual({ emit: true, suppressed: 0 });
    now = 1_000;
    expect(throttle("/api/inventory/products|503").emit).toBe(false);
    expect(throttle("/api/inventory/products|503").emit).toBe(false);
    expect(throttle("/api/incidents|503").emit).toBe(true);
    now = 31_000;
    expect(throttle("/api/inventory/products|503")).toEqual({ emit: true, suppressed: 2 });
  });

  it("limita el total por hora", () => {
    let now = 0;
    const throttle = createWindowThrottle(60_000, 2, () => now);
    expect(throttle("a").emit).toBe(true);
    expect(throttle("b").emit).toBe(true);
    expect(throttle("c").emit).toBe(false);
    now = 3_600_000;
    expect(throttle("c")).toEqual({ emit: true, suppressed: 1 });
  });
});

describe("identificadores de inventario", () => {
  // Mismos casos que tests/telemetry/test_inventory_events.py: la API y el
  // navegador tienen que producir el mismo client_id.
  it.each([
    ["PureStep Footwear", "purestep-footwear"],
    ["SoundWave Electrónica", "soundwave-electronica"],
    ["  Glow & Co.  ", "glow-co"],
    ["L'Oréal España", "l-oreal-espana"],
    ["¿¿??", "unknown"],
  ])("clientId(%s) = %s", (name, slug) => {
    expect(clientId(name)).toBe(slug);
  });

  it("traduce el SKU al vocabulario del plan", () => {
    expect(inventoryIdentity(sku)).toEqual({
      warehouse: "zaragoza",
      country: "ES",
      client_id: "soundwave-electronica",
      product_id: "TEC-CHG-065",
      product_category: "electronics",
    });
  });

  it("la validación del cliente registra campos y tipos, nunca valores", () => {
    const event = clientValidationFailure(
      "outbound_order",
      { skuId: "6", quantity: "abc", exitType: "dispatch", trackingNumber: "" },
      { quantity: "Indica un número entero…", trackingNumber: "Falta el seguimiento" },
      sku,
    );
    expect(event).toEqual({
      layer: "client",
      operation: "outbound_order",
      product_id: "TEC-CHG-065",
      warehouse: "zaragoza",
      client_id: "soundwave-electronica",
      error_fields: ["quantity", "tracking_number"],
      error_types: ["value_error", "missing"],
      error_count: 2,
    });
    expect(JSON.stringify(event)).not.toContain("abc");
  });

  it("el punto de entrada distingue fila de la tabla, menú lateral y URL directa", () => {
    expect(inventoryEntryPoint("/inventory/orders/outbound", true)).toBe("stock_table_row");
    expect(inventoryEntryPoint("/inventory/orders/outbound", false)).toBe("direct_url");
    rememberSidebarNavigation("/inventory/orders/outbound");
    expect(inventoryEntryPoint("/inventory/orders/outbound", false)).toBe("sidebar");
    expect(inventoryEntryPoint("/inventory/orders/inbound", false)).toBe("direct_url");
  });
});
