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


class UserCreate(ProfileFields):
    email: EmailStr
    password: NewPassword


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: NewPassword | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class ProfileUpdate(ProfileFields):
    pass


class User(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str
    email: EmailStr
    hashed_password: str
    is_active: bool
    role: UserRole
    created_at: datetime


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    is_active: bool
    role: UserRole
    created_at: datetime


class Profile(ProfileFields):
    id: str
    user_id: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: NewPassword


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: NewPassword


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    email: EmailStr
    role: UserRole
    profile: Profile