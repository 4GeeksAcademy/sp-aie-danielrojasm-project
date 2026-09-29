/** FE-019: utilidades del gestor de incidencias (`lib/incidents.ts`). */
import { ApiError, NETWORK_ERROR_STATUS } from "@/lib/api-client";
import {
  TITLE_MAX_LENGTH,
  formatIncidentDate,
  incidentFieldMessages,
  toFriendlyError,
  validateIncidentForm,
  type IncidentFormValues,
} from "@/lib/incidents";

function values(overrides: Partial<IncidentFormValues> = {}): IncidentFormValues {
  return {
    title: "Paquete perdido en reparto",
    description: "El cliente no recibió el pedido 4411.",
    category: "lost_parcel",
    origin: "customer",
    branch: "la_warehouse",
    ...overrides,
  };
}

describe("validateIncidentForm", () => {
  it("acepta un formulario completo", () => {
    expect(validateIncidentForm(values())).toEqual({});
  });

  it("acepta un título de exactamente 120 caracteres", () => {
    expect(validateIncidentForm(values({ title: "x".repeat(TITLE_MAX_LENGTH) }))).toEqual({});
  });

  it("rechaza títulos vacíos, solo con espacios o demasiado largos", () => {
    for (const title of ["", "   ", "x".repeat(TITLE_MAX_LENGTH + 1)]) {
      expect(validateIncidentForm(values({ title })).title).toBe(incidentFieldMessages.title);
    }
  });

  it("marca cada selector sin valor", () => {
    const errors = validateIncidentForm(values({ category: "", origin: "", branch: "", description: " " }));
    expect(Object.keys(errors).sort()).toEqual(["branch", "category", "description", "origin"]);
  });
});

describe("toFriendlyError", () => {
  it("asigna los errores 400 de la API a los campos del formulario", () => {
    const error = new ApiError("400", 400, {
      errors: [
        { field: "title", message: "String should have at most 120 characters" },
        { field: "reported_by", message: "extra field" },
      ],
    });
    const friendly = toFriendlyError(error, "registrar la incidencia");
    // Se muestra el texto propio de la UI, no el técnico; los campos ajenos al formulario se ignoran.
    expect(friendly.fields).toEqual({ title: incidentFieldMessages.title });
    expect(friendly.message).toBe("Revisa los campos marcados antes de volver a enviar.");
  });

  it("un 400 sin campos conocidos da un mensaje general", () => {
    const friendly = toFriendlyError(new ApiError("400", 400, { errors: [] }), "cambiar el estado");
    expect(friendly.fields).toEqual({});
    expect(friendly.message).toContain("No se pudo cambiar el estado");
  });

  it.each([
    [NETWORK_ERROR_STATUS, "no hay conexión"],
    [401, "sesión ha caducado"],
    [404, "ya no existe"],
    [503, "no responde"],
  ])("traduce el estado %s", (status, fragment) => {
    expect(toFriendlyError(new ApiError("x", status), "cargar").message).toContain(fragment);
  });

  it("trata un error que no es de la API como fallo de conexión", () => {
    expect(toFriendlyError(new Error("boom"), "cargar").message).toContain("no hay conexión");
  });
});

describe("formatIncidentDate", () => {
  it("formatea una fecha ISO en español", () => {
    const text = formatIncidentDate("2026-03-05T10:30:00Z");
    expect(text).toMatch(/2026/);
    expect(text).toMatch(/mar/i);
  });

  it("no lanza con una fecha inválida", () => {
    // Antes Intl lanzaba RangeError y rompía todo el listado.
    expect(formatIncidentDate("no-es-una-fecha")).toBe("Fecha no disponible");
  });
});
