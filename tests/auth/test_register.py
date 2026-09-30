"""POST /users — registro de credenciales y perfil (`register_user`)."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api.auth_models import UserCreate
from services.api.passwords import verify_password
from services.api.routes.users import register_user
from services.api.user_service import get_profile_by_user_id, get_user_by_email


# --- Camino feliz -----------------------------------------------------------

def test_register_creates_active_user_with_hashed_password_and_profile():
    user = register_user(
        UserCreate(
            email="Ana.Whitfield@TrackFlow.example",
            password="warehouse-2026",
            name="Ana Whitfield",
            phone="+1 555 0100",
        )
    )

    # La respuesta no reenvía el email ni ninguna credencial.
    assert set(user.model_dump()) == {"id", "role", "created_at"}
    assert user.role == "user"  # nunca se registra como admin

    stored = get_user_by_email("ana.whitfield@trackflow.example")  # normalizado
    assert stored is not None and stored.id == user.id
    assert stored.is_active is True
    assert stored.hashed_password != "warehouse-2026"
    assert verify_password("warehouse-2026", stored.hashed_password)

    profile = get_profile_by_user_id(user.id)
    assert profile is not None
    assert (profile.name, profile.phone, profile.address) == (
        "Ana Whitfield",
        "+1 555 0100",
        None,
    )


# --- Casos límite -----------------------------------------------------------

def test_password_of_exactly_eight_characters_is_accepted():
    register_user(UserCreate(email="min@example.com", password="12345678"))
    assert verify_password("12345678", get_user_by_email("min@example.com").hashed_password)


def test_password_of_seven_characters_is_rejected():
    with pytest.raises(ValidationError) as error:
        UserCreate(email="min@example.com", password="1234567")
    assert error.value.errors()[0]["loc"] == ("password",)


def test_duplicate_email_differing_only_in_case_is_rejected():
    register_user(UserCreate(email="carlos@example.com", password="carrier-ops-1"))

    with pytest.raises(HTTPException) as error:
        register_user(UserCreate(email="CARLOS@example.com", password="other-password"))

    assert error.value.status_code == 409
    # El primer registro se conserva intacto.
    stored = get_user_by_email("carlos@example.com")
    assert stored is not None
    assert verify_password("carrier-ops-1", stored.hashed_password)


def test_profile_fields_are_optional():
    user = register_user(UserCreate(email="solo@example.com", password="long-enough"))
    profile = get_profile_by_user_id(user.id)
    assert profile is not None
    assert (profile.name, profile.phone, profile.address) == (None, None, None)


def test_multibyte_password_within_72_bytes_is_accepted():
    # 36 «ñ» = 72 bytes UTF-8: justo el límite de bcrypt.
    password = "ñ" * 36
    register_user(UserCreate(email="es@example.com", password=password))
    assert verify_password(password, get_user_by_email("es@example.com").hashed_password)


# --- Modos de fallo ---------------------------------------------------------

@pytest.mark.parametrize(
    ("email", "password", "field"),
    [
        ("ana@example.com", "", "password"),
        ("not-an-email", "long-enough", "email"),
        ("", "long-enough", "email"),
    ],
)
def test_invalid_registration_data_is_rejected(email, password, field):
    with pytest.raises(ValidationError) as error:
        UserCreate(email=email, password=password)
    assert error.value.errors()[0]["loc"] == (field,)


def test_password_longer_than_72_bytes_is_rejected_before_hashing():
    # Bug detectado por la batería: 40 «ñ» son 40 caracteres (pasaban
    # max_length=72) pero 80 bytes, y bcrypt lanzaba ValueError → error 500.
    with pytest.raises(ValidationError) as error:
        UserCreate(email="es@example.com", password="ñ" * 40)
    assert error.value.errors()[0]["loc"] == ("password",)
