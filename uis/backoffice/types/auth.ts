export type UserRole = "admin" | "manager" | "user";

/** Datos de contacto editables; la API no expone las claves internas del perfil. */
export interface Profile {
  name: string | null;
  phone: string | null;
  address: string | null;
}

export interface AuthUser {
  id: string;
  email: string;
  role: UserRole;
  profile: Profile;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegistrationData extends LoginCredentials {
  name?: string;
  phone?: string;
  address?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
}