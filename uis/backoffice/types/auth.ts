export type UserRole = "admin" | "manager" | "user";

export interface Profile {
  id: string;
  user_id: string;
  name: string | null;
  phone: string | null;
  address: string | null;
}

export interface AuthUser {
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