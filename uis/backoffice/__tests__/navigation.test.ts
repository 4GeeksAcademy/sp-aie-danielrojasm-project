/** Navegación de punta a punta: cada ruta de `app/` cuelga de una entrada del menú. */
import fs from "node:fs";
import path from "node:path";
import { PUBLIC_ROUTES, findActiveNavKey, navSections } from "@/lib/navigation";

const APP_DIR = path.join(__dirname, "..", "app");

/** Rutas del App Router; los segmentos dinámicos (`[ticketId]`) se sustituyen por un valor de ejemplo. */
function appRoutes(dir = APP_DIR, segments: string[] = []): string[] {
  const routes: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      const segment = entry.name.startsWith("[") ? "ejemplo" : entry.name;
      routes.push(...appRoutes(path.join(dir, entry.name), [...segments, segment]));
    } else if (entry.name === "page.tsx") {
      routes.push(`/${segments.join("/")}`);
    }
  }
  return routes;
}

const items = navSections.flatMap((section) => section.items);

describe("mapa de navegación", () => {
  it("cada ruta privada pertenece a un ítem del menú", () => {
    const orphans = appRoutes()
      .filter((route) => !PUBLIC_ROUTES.has(route))
      .filter((route) => findActiveNavKey(route) === null);
    expect(orphans).toEqual([]);
  });

  it("cada ítem activo apunta a una página existente", () => {
    const routes = new Set(appRoutes());
    const broken = items
      .filter((item) => !item.upcoming)
      .map((item) => item.href.split("#")[0] || "/")
      .filter((href) => !routes.has(href));
    expect(broken).toEqual([]);
  });

  it("las claves de telemetría no se repiten", () => {
    const keys = items.map((item) => item.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("findActiveNavKey", () => {
  it("elige el prefijo más largo", () => {
    expect(findActiveNavKey("/inventory/orders")).toBe("inventory_history");
    expect(findActiveNavKey("/inventory/orders/inbound")).toBe("inventory_inbound");
    expect(findActiveNavKey("/inventory")).toBe("inventory_stock");
  });

  it("marca el módulo padre en las rutas hijas", () => {
    expect(findActiveNavKey("/rfps/RFP-123")).toBe("rfp_intake");
    expect(findActiveNavKey("/account/change-password")).toBe("profile");
  });

  it("solo marca el panel en la raíz", () => {
    expect(findActiveNavKey("/")).toBe("dashboard");
    expect(findActiveNavKey("/desconocida")).toBeNull();
    expect(findActiveNavKey("/rfpsx")).toBeNull();
  });
});
