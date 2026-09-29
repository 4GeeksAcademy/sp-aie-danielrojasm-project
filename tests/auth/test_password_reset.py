"""POST /auth/forgot-password, /auth/reset-password y /auth/change-password."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from jose import jwt

from services.api.auth_models import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UserUpdate,
)
from services.api.database import get_auth_db
from services.api.passwords import verify_password
from services.api.reset_email import EmailDeliveryError
from services.api.routes.auth import change_password, forgot_password, reset_password
from services.api.security import ALGORITHM
from services.api.user_service import delete_user, get_user_by_id, update_user
from tests.helpers import DEFAULT_PASSWORD, TEST_SECRET

SEND_EMAIL = "services.api.routes.auth.send_reset_email"


def request_link(email: str = "ana@example.com") -> tuple[dict, str | None]:
    """Pide un enlace y devuelve la respuesta y el token enviado (o None)."""
    with patch(SEND_EMAIL) as send_email:
        response = forgot_password(ForgotPasswordRequest(email=email))
    if not send_email.called:
        return response, None
    _, link = send_email.call_args.args
    return response, parse_qs(urlparse(link).query)["token"][0]


def stored_reset_hashes() -> list[str]:
    with get_auth_db() as db:
        return [row["token_hash"] for row in db.table("password_resets").all()]


# --- forgot-password --------------------------------------------------------

def test_forgot_password_sends_link_and_stores_only_the_hash(make_user):
    make_user()
    _, token = request_link()

    assert token is not None
    # En base de datos solo está el hash: una fuga de auth.json no permite resetear.
    assert stored_reset_hashes() == [sha256(token.encode()).hexdigest()]


def test_forgot_password_gives_same_answer_for_unknown_and_inactive_accounts(make_user):
    known, _ = request_link()  # todavía no existe
    user = make_user()
    update_user(user.id, UserUpdate(is_active=False))
    inactive, token = request_link()

    assert known == inactive  # no revela si la cuenta existe
    assert token is None  # y no se envía nada
    assert stored_reset_hashes() == []


def test_new_link_invalidates_the_previous_one(make_user):
    make_user()
    _, first = request_link()
    _, second = request_link()

    with pytest.raises(HTTPException):
        reset_password(ResetPasswordRequest(token=first, new_password="first-attempt"))
    reset_password(ResetPasswordRequest(token=second, new_password="second-attempt"))


def test_codespaces_link_points_to_forwarded_port(make_user, monkeypatch):
    monkeypatch.setenv("PASSWORD_RESET_URL", "http://localhost:3002/reset-password")
    monkeypatch.setenv("CODESPACE_NAME", "trackflow-space")
    monkeypatch.setenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    make_user()

    with patch(SEND_EMAIL) as send_email:
        forgot_password(ForgotPasswordRequest(email="ana@example.com"))

    link = urlparse(send_email.call_args.args[1])
    assert (link.scheme, link.netloc, link.path) == (
        "https",
        "trackflow-space-3002.app.github.dev",
        "/reset-password",
    )


def test_email_provider_failure_keeps_generic_answer(make_user, caplog):
    make_user()
    with patch(SEND_EMAIL, side_effect=EmailDeliveryError("Resend rechazó el envío")):
        response = forgot_password(ForgotPasswordRequest(email="ana@example.com"))

    assert response == request_link("nobody@example.com")[0]
    # Queda registrado para soporte, sin el email del usuario.
    assert "Resend rechazó el envío" in caplog.text
    assert "ana@example.com" not in caplog.text


# --- reset-password ---------------------------------------------------------

def test_reset_changes_password_and_consumes_token(make_user):
    user = make_user()
    _, token = request_link()

    reset_password(ResetPasswordRequest(token=token, new_password="new-password-1"))

    assert verify_password("new-password-1", get_user_by_id(user.id).hashed_password)
    assert stored_reset_hashes() == []


def test_reset_token_cannot_be_reused(make_user):
    make_user()
    _, token = request_link()
    reset_password(ResetPasswordRequest(token=token, new_password="new-password-1"))

    with pytest.raises(HTTPException) as error:
        reset_password(ResetPasswordRequest(token=token, new_password="new-password-2"))
    assert error.value.status_code == 400


def test_reset_fails_for_expired_forged_or_unknown_tokens(make_user):
    user = make_user()
    expired = jwt.encode(
        {"sub": user.id, "purpose": "password-reset", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        TEST_SECRET,
        algorithm=ALGORITHM,
    )
    # Firmado y vigente, pero nunca emitido por forgot-password (sin hash guardado).
    never_issued = jwt.encode(
        {"sub": user.id, "purpose": "password-reset", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        TEST_SECRET,
        algorithm=ALGORITHM,
    )
    for token in (expired, never_issued, "garbage"):
        with pytest.raises(HTTPException) as error:
            reset_password(ResetPasswordRequest(token=token, new_password="new-password-1"))
        assert error.value.status_code == 400
    assert verify_password(DEFAULT_PASSWORD, get_user_by_id(user.id).hashed_password)


def test_reset_fails_if_account_was_deleted(make_user):
    user = make_user()
    _, token = request_link()
    delete_user(user.id)
    with pytest.raises(HTTPException) as error:
        reset_password(ResetPasswordRequest(token=token, new_password="new-password-1"))
    assert error.value.status_code == 400


# --- change-password --------------------------------------------------------

def test_change_password_with_correct_current_password(make_user):
    user = make_user()
    change_password(
        ChangePasswordRequest(current_password=DEFAULT_PASSWORD, new_password="rotated-password"),
        user,
    )
    assert verify_password("rotated-password", get_user_by_id(user.id).hashed_password)


def test_change_password_revokes_pending_reset_links(make_user):
    user = make_user()
    _, token = request_link()
    change_password(
        ChangePasswordRequest(current_password=DEFAULT_PASSWORD, new_password="rotated-password"),
        user,
    )
    with pytest.raises(HTTPException):
        reset_password(ResetPasswordRequest(token=token, new_password="attacker-choice"))


def test_change_password_rejects_wrong_current_password(make_user):
    user = make_user()
    with pytest.raises(HTTPException) as error:
        change_password(
            ChangePasswordRequest(current_password="guess", new_password="rotated-password"),
            user,
        )
    assert error.value.status_code == 400
    assert verify_password(DEFAULT_PASSWORD, get_user_by_id(user.id).hashed_password)
