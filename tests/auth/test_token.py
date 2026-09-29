"""Tokens JWT: emisión (`create_access_token`) y validación (`get_current_user`).

Es el módulo que cubre la regresión que originó AUTH-088: un token caducado
tiene que rechazarse siempre, y uno vigente aceptarse hasta el último segundo.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

from services.api.auth_models import UserUpdate
from services.api.security import (
    ALGORITHM,
    create_access_token,
    create_reset_token,
    get_current_user,
    reset_token_user_id,
)
from services.api.user_service import delete_user, update_user
from tests.helpers import TEST_SECRET


def claims(token: str) -> dict:
    return jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])


def assert_unauthorized(token: str) -> None:
    with pytest.raises(HTTPException) as error:
        get_current_user(token)
    assert error.value.status_code == 401
    # El cliente necesita la cabecera para saber que debe volver a autenticarse.
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


# --- Camino feliz -----------------------------------------------------------

def test_valid_token_resolves_to_its_user(make_user):
    user = make_user()
    assert get_current_user(create_access_token(user.id)).id == user.id


def test_expiration_follows_configured_minutes(make_user, monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "5")
    user = make_user()

    expires_in = claims(create_access_token(user.id))["exp"] - datetime.now(timezone.utc).timestamp()

    assert 4 * 60 < expires_in <= 5 * 60


# --- Casos límite -----------------------------------------------------------

def test_token_about_to_expire_is_still_accepted(make_user):
    user = make_user()
    token = create_access_token(user.id, expires_delta=timedelta(seconds=5))
    assert get_current_user(token).id == user.id


def test_token_expired_one_second_ago_is_rejected(make_user):
    user = make_user()
    assert_unauthorized(create_access_token(user.id, expires_delta=timedelta(seconds=-1)))


def test_explicit_expiration_overrides_configuration(make_user):
    user = make_user()
    token = create_access_token(user.id, expires_delta=timedelta(days=1))
    expires_in = claims(token)["exp"] - datetime.now(timezone.utc).timestamp()
    assert expires_in > 23 * 3600


# --- Modos de fallo ---------------------------------------------------------

def test_expired_token_is_rejected(make_user):
    # La regresión original: tokens de hace horas seguían siendo válidos.
    user = make_user()
    assert_unauthorized(create_access_token(user.id, expires_delta=timedelta(hours=-2)))


@pytest.mark.parametrize(
    "token",
    ["", "not-a-jwt", "a.b.c", "Bearer abc.def.ghi"],
    ids=["vacio", "texto", "tres-segmentos", "con-prefijo"],
)
def test_malformed_token_is_rejected(token):
    assert_unauthorized(token)


def test_token_signed_with_another_secret_is_rejected(make_user):
    user = make_user()
    forged = jwt.encode(
        {"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "another-secret-key-with-at-least-32-chars",
        algorithm=ALGORITHM,
    )
    assert_unauthorized(forged)


def test_tampered_payload_is_rejected(make_user):
    victim = make_user()
    attacker = make_user(email="attacker@example.com")
    header, _, signature = create_access_token(attacker.id).split(".")
    # Se sustituye el payload por el de otra cuenta manteniendo la firma.
    victim_payload = create_access_token(victim.id).split(".")[1]
    assert_unauthorized(f"{header}.{victim_payload}.{signature}")


def test_token_without_subject_is_rejected():
    token = jwt.encode(
        {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        TEST_SECRET,
        algorithm=ALGORITHM,
    )
    assert_unauthorized(token)


def test_password_reset_token_cannot_be_used_as_access_token(make_user):
    user = make_user()
    assert_unauthorized(create_reset_token(user.id))


def test_token_of_deleted_user_is_rejected(make_user):
    user = make_user()
    token = create_access_token(user.id)
    delete_user(user.id)
    assert_unauthorized(token)


def test_token_of_deactivated_user_is_rejected(make_user):
    user = make_user()
    token = create_access_token(user.id)
    update_user(user.id, UserUpdate(is_active=False))
    assert_unauthorized(token)


def test_missing_secret_is_a_server_error_not_bad_credentials(make_user, monkeypatch):
    # Un fallo de configuración no debe disfrazarse de "credenciales no
    # válidas": sube como RuntimeError y el handler global responde 500.
    user = make_user()
    token = create_access_token(user.id)
    monkeypatch.delenv("JWT_SECRET_KEY")

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        get_current_user(token)
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        create_access_token(user.id)


@pytest.mark.parametrize("minutes", ["0", "-5", "treinta"])
def test_invalid_expiration_setting_is_a_server_error(make_user, monkeypatch, minutes):
    user = make_user()
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", minutes)
    with pytest.raises(RuntimeError, match="ACCESS_TOKEN_EXPIRE_MINUTES"):
        create_access_token(user.id)


# --- Tokens de recuperación -------------------------------------------------

def test_reset_token_identifies_user_and_expires_in_30_minutes(make_user):
    user = make_user()
    token = create_reset_token(user.id)

    assert reset_token_user_id(token) == user.id
    expires_in = claims(token)["exp"] - datetime.now(timezone.utc).timestamp()
    assert 29 * 60 < expires_in <= 30 * 60


def test_access_token_is_not_accepted_as_reset_token(make_user):
    user = make_user()
    assert reset_token_user_id(create_access_token(user.id)) is None


def test_expired_or_garbage_reset_token_is_rejected(make_user):
    user = make_user()
    expired = jwt.encode(
        {
            "sub": user.id,
            "purpose": "password-reset",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        TEST_SECRET,
        algorithm=ALGORITHM,
    )
    assert reset_token_user_id(expired) is None
    assert reset_token_user_id("garbage") is None
