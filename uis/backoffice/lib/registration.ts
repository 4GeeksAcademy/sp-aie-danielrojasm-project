export type RegistrationField =
  | "email"
  | "password"
  | "confirmPassword"
  | "name"
  | "phone"
  | "address";

export type RegistrationErrors = Partial<Record<RegistrationField, string>>;

export const PASSWORD_MIN_LENGTH = 8;
// bcrypt solo admite 72 bytes: con acentos o "ñ" se llega antes que a 72
// caracteres. La API aplica el mismo límite en bytes.
export const PASSWORD_MAX_BYTES = 72;

export function validateRegistration(formData: FormData): RegistrationErrors {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const confirmPassword = String(formData.get("confirmPassword") ?? "");
  const errors: RegistrationErrors = {};

  if (!email) errors.email = "Introduce tu email.";
  else if (!/^\S+@\S+\.\S+$/.test(email)) errors.email = "Introduce un email válido.";
  if (password.length < PASSWORD_MIN_LENGTH) {
    errors.password = `Usa al menos ${PASSWORD_MIN_LENGTH} caracteres.`;
  } else if (new TextEncoder().encode(password).length > PASSWORD_MAX_BYTES) {
    errors.password = "La contraseña es demasiado larga: acórtala o usa menos caracteres acentuados.";
  }
  if (confirmPassword !== password) errors.confirmPassword = "Las contraseñas no coinciden.";
  return errors;
}
