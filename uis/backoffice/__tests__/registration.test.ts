/** Validación del registro en cliente (`lib/registration.ts`). */
import { validateRegistration } from "@/lib/registration";

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) data.set(key, value);
  return data;
}

function registration(overrides: Record<string, string> = {}): FormData {
  const password = overrides.password ?? "correct-password";
  return form({ email: "ana@example.com", password, confirmPassword: password, ...overrides });
}

describe("validateRegistration", () => {
  it("acepta datos válidos", () => {
    expect(validateRegistration(registration())).toEqual({});
  });

  it("ignora espacios alrededor del email", () => {
    expect(validateRegistration(registration({ email: "  ana@example.com " }))).toEqual({});
  });

  it("exige email y rechaza uno mal formado", () => {
    expect(validateRegistration(registration({ email: "   " })).email).toBe("Introduce tu email.");
    expect(validateRegistration(registration({ email: "ana@example" })).email).toBe(
      "Introduce un email válido.",
    );
  });

  it("acepta exactamente 8 caracteres y rechaza 7", () => {
    expect(validateRegistration(registration({ password: "12345678" })).password).toBeUndefined();
    expect(validateRegistration(registration({ password: "1234567" })).password).toBeDefined();
  });

  it("mide el máximo en bytes, como bcrypt en la API", () => {
    // 72 caracteres ASCII caben; 40 "ñ" son 40 caracteres pero 80 bytes.
    expect(validateRegistration(registration({ password: "a".repeat(72) })).password).toBeUndefined();
    expect(validateRegistration(registration({ password: "a".repeat(73) })).password).toBeDefined();
    expect(validateRegistration(registration({ password: "ñ".repeat(40) })).password).toBeDefined();
  });

  it("detecta una confirmación distinta", () => {
    const errors = validateRegistration(registration({ confirmPassword: "otra-password" }));
    expect(errors).toEqual({ confirmPassword: "Las contraseñas no coinciden." });
  });

  it("señala todos los campos cuando el formulario llega vacío", () => {
    expect(Object.keys(validateRegistration(form({}))).sort()).toEqual(["email", "password"]);
  });
});
