/** TRK-0341: utilidades y cliente del inventario (`lib/inventory.ts`). */
import { ApiError } from "@/lib/api-client";
import {
  LOW_STOCK_THRESHOLD,
  createStockExit,
  formatOrderDate,
  getOverdraftWarning,
  getSKU,
  getStockLevel,
  listInventoryOrders,
  parseQuantity,
  parseSkuParam,
  validateStockEntry,
  validateStockExit,
} from "@/lib/inventory";

function installWindow(token: string | null = "token-de-prueba") {
  const store = new Map<string, string>(token ? [["trackflow_access_token", token]] : []);
  Object.assign(globalThis, {
    window: {
      localStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => void store.set(key, value),
        removeItem: (key: string) => void store.delete(key),
      },
      location: { pathname: "/inventory/orders/outbound", assign: jest.fn() },
    },
  });
}

function mockFetch(body: unknown, status: number) {
  const fetchMock = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    void input;
    void init;
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

beforeEach(() => installWindow());
afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
  jest.restoreAllMocks();
});

describe("getStockLevel", () => {
  it("distingue sin stock, bajo y saludable en los umbrales", () => {
    expect(getStockLevel(0)).toBe("out");
    expect(getStockLevel(-3)).toBe("out");
    expect(getStockLevel(1)).toBe("low");
    expect(getStockLevel(LOW_STOCK_THRESHOLD - 1)).toBe("low");
    expect(getStockLevel(LOW_STOCK_THRESHOLD)).toBe("healthy");
  });
});

describe("parseQuantity", () => {
  it("solo acepta enteros positivos", () => {
    expect(parseQuantity(" 12 ")).toBe(12);
    for (const value of ["", "0", "-4", "2.5", "1e3", "abc"]) {
      expect(parseQuantity(value)).toBeNull();
    }
  });
});

describe("validateStockEntry", () => {
  it("acepta una recepción completa", () => {
    expect(validateStockEntry({ skuId: "1", quantity: "40", reference: "PO-2024-0098" })).toEqual({});
  });

  it("marca SKU, cantidad y referencia vacíos o demasiado largos", () => {
    expect(Object.keys(validateStockEntry({ skuId: "", quantity: "0", reference: "  " })).sort()).toEqual([
      "quantity",
      "reference",
      "skuId",
    ]);
    expect(validateStockEntry({ skuId: "1", quantity: "1", reference: "x".repeat(101) }).reference).toMatch(
      /100 caracteres/,
    );
  });
});

describe("validateStockExit", () => {
  it("un despacho necesita número de seguimiento", () => {
    const errors = validateStockExit({ skuId: "1", quantity: "3", exitType: "dispatch", trackingNumber: " " });
    expect(Object.keys(errors)).toEqual(["trackingNumber"]);
  });

  it("una pérdida no lo necesita", () => {
    expect(validateStockExit({ skuId: "1", quantity: "3", exitType: "loss", trackingNumber: "" })).toEqual({});
  });
});

describe("getOverdraftWarning", () => {
  it("avisa solo si la cantidad supera el stock mostrado", () => {
    expect(getOverdraftWarning("41", 40)).toMatch(/Solo hay 40 unidades.*sacar 41/);
    expect(getOverdraftWarning("40", 40)).toBeNull();
    expect(getOverdraftWarning("41", null)).toBeNull();
    expect(getOverdraftWarning("", 40)).toBeNull();
  });
});

describe("formato", () => {
  it("una fecha inválida no rompe el historial", () => {
    expect(formatOrderDate("no-es-fecha")).toBe("Fecha no disponible");
    expect(formatOrderDate("2026-09-29T22:00:21Z")).toMatch(/2026/);
  });

  it("parseSkuParam solo deja pasar ids numéricos", () => {
    expect(parseSkuParam("6")).toBe("6");
    expect(parseSkuParam(["3", "4"])).toBe("3");
    expect(parseSkuParam("6;drop")).toBe("");
    expect(parseSkuParam(undefined)).toBe("");
  });
});

describe("cliente de /inventory", () => {
  it("envía el token del usuario en la cabecera Authorization", async () => {
    const fetchMock = mockFetch([], 200);
    await listInventoryOrders();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/inventory/orders");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer token-de-prueba");
  });

  it("consulta el stock de un SKU por su id", async () => {
    const fetchMock = mockFetch({ id: 6, current_stock: 40 }, 200);
    await expect(getSKU(6)).resolves.toMatchObject({ current_stock: 40 });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/inventory/products/6");
  });

  it("un 400 por stock insuficiente llega con el mensaje de la API", async () => {
    const detail = "Insufficient stock for SKU 'TEC-CHG-065'. Available: 40, requested: 41.";
    const fetchMock = mockFetch({ detail }, 400);
    const error = await createStockExit({
      sku_id: 6,
      quantity: 41,
      exit_type: "loss",
      tracking_number: null,
      warehouse: "ZGZ",
    }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(400);
    expect((error as ApiError).message).toBe(detail);
    const init = fetchMock.mock.calls[0][1];
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toMatchObject({ sku_id: 6, quantity: 41, warehouse: "ZGZ" });
  });

  it("un 500 no enseña el cuerpo crudo", async () => {
    mockFetch({ detail: "Traceback: psycopg2.OperationalError" }, 500);
    const error = (await getSKU(1).catch((caught: unknown) => caught)) as ApiError;
    expect(error.message).not.toMatch(/psycopg2/);
  });
});
