from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from services.api.passwords import MAX_PASSWORD_BYTES, exceeds_bcrypt_limit


def _fits_bcrypt(password: str) -> str:
    if exceeds_bcrypt_limit(password):
        raise ValueError(
            f"La contraseña no puede superar {MAX_PASSWORD_BYTES} bytes: "
            "acórtala o usa menos caracteres acentuados."
        )
    return password


NewPassword = Annotated[str, Field(min_length=8, max_length=72), AfterValidator(_fits_bcrypt)]


class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"


class ProfileFields(BaseModel):
    name: str | None = None
    phone: str | None = None
    address: str | None = None


# ---------------------------------------------------------------------------
# Entrada: solo los campos que el cliente puede escribir. `extra="forbid"`
# responde 422 ante cualquier otro (p. ej. `role` o `is_active` en el alta).
# ---------------------------------------------------------------------------

class UserCreate(ProfileFields):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: NewPassword


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    password: NewPassword | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class ProfileUpdate(ProfileFields):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    new_password: NewPassword


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: NewPassword


# ---------------------------------------------------------------------------
# Modelos internos (TinyDB). Nunca se declaran como `response_model`: `User`
# lleva `hashed_password` y `Profile` las claves `id`/`user_id`.
# ---------------------------------------------------------------------------

class User(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str
    email: EmailStr
    hashed_password: str
    is_active: bool
    role: UserRole
    created_at: datetime


class Profile(ProfileFields):
    id: str
    user_id: str


# ---------------------------------------------------------------------------
# Salida: proyecciones explícitas por endpoint.
# ---------------------------------------------------------------------------

class UserRegistered(BaseModel):
    """Alta pública: sin email (ya va en la petición) ni credenciales."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    role: UserRole
    created_at: datetime


class UserRead(BaseModel):
    """Detalle de una cuenta para su dueño o un admin (sesión obligatoria)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime


class UserListItem(BaseModel):
    """Fila del listado de admin: lo justo para identificar y gestionar la cuenta."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    role: UserRole
    is_active: bool


class ProfileRead(ProfileFields):
    """Datos de contacto editables, sin las claves internas del documento."""

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    """`GET /auth/me`: el propio llamante, por eso sí incluye su email."""

    id: str
    email: EmailStr
    role: UserRole
    profile: ProfileRead
