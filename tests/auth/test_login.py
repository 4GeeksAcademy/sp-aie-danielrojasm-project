"""POST /auth/login — autenticación con email y contraseña (`login`)."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

from services.api.auth_models import UserUpdate
from services.api.routes.auth import login
from services.api.security import ALGORITHM
from services.api.user_service import update_user
from tests.helpers import DEFAULT_PASSWORD, TEST_SECRET, FakeRequest, run


def decode(token: str) -> dict:
    return jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])


def attempt_login(email: str, password: str) -> str:
    response = run(login(FakeRequest({"email": email, "password": password})))
    return response.access_token


# --- Camino feliz -----------------------------------------------------------

def test_valid_credentials_issue_token_for_that_user(make_user):
    user = make_user()

    claims = decode(attempt_login("ana@example.com", DEFAULT_PASSWORD))

    assert claims["sub"] == user.id
    assert "purpose" not in claims  # es un token de acceso, no de recuperación
    minutes_left = (claims["exp"] - datetime.now(timezone.utc).timestamp()) / 60
    assert 29 < minutes_left <= 30  # ACCESS_TOKEN_EXPIRE_MINUTES=30


def test_oauth2_form_uses_username_as_email(make_user):
    # Swagger envía el formulario OAuth2 con el email en `username`.
    user = make_user()
    response = run(
        login(FakeRequest(form={"username": "ana@example.com", "password": DEFAULT_PASSWORD}))
    )
    assert decode(response.access_token)["sub"] == user.id


# --- Casos límite -----------------------------------------------------------

def test_email_is_case_insensitive(make_user):
    user = make_user()
    assert decode(attempt_login("ANA@Example.COM", DEFAULT_PASSWORD))["sub"] == user.id


def test_password_longer_than_72_bytes_is_a_wrong_password_not_a_crash(make_user):
    # Antes lanzaba ValueError desde bcrypt (500). Ninguna contraseña guardada
    # puede superar el límite, así que debe tratarse como incorrecta.
    make_user()
    with pytest.raises(HTTPException) as error:
        attempt_login("ana@example.com", "ñ" * 40)
    assert error.value.status_code == 401


# --- Modos de fallo ---------------------------------------------------------

def test_wrong_password_and_unknown_email_are_indistinguishable(make_user):
    make_user()

    with pytest.raises(HTTPException) as wrong_password:
        attempt_login("ana@example.com", "incorrect-password")
    with pytest.raises(HTTPException) as unknown_email:
        attempt_login("nobody@example.com", DEFAULT_PASSWORD)

    assert wrong_password.value.status_code == unknown_email.value.status_code == 401
    # Mismo mensaje: la respuesta no revela qué emails tienen cuenta.
    assert wrong_password.value.detail == unknown_email.value.detail


def test_deactivated_user_cannot_log_in(make_user):
    user = make_user()
    update_user(user.id, UserUpdate(is_active=False))

    with pytest.raises(HTTPException) as error:
        attempt_login("ana@example.com", DEFAULT_PASSWORD)
    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "request_",
    [
        FakeRequest({"email": "ana@example.com"}),
        FakeRequest({"email": "ana@example.com", "password": ""}),
        FakeRequest({"password": DEFAULT_PASSWORD}),
        FakeRequest(raw_json="{not json"),
        FakeRequest(form={"username": "ana@example.com"}),
    ],
    ids=["sin-password", "password-vacia", "sin-email", "json-invalido", "form-sin-password"],
)
def test_incomplete_or_malformed_login_is_rejected(make_user, request_):
    make_user()
    with pytest.raises(HTTPException) as error:
        run(login(request_))
    assert error.value.status_code == 422
