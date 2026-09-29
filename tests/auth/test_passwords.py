"""Hash de contraseñas (`hash_password`, `verify_password`) y límite de bcrypt."""

import pytest
from pydantic import ValidationError

from services.api.auth_models import ChangePasswordRequest, ResetPasswordRequest, UserUpdate
from services.api.passwords import exceeds_bcrypt_limit, hash_password, verify_password


def test_hash_verifies_only_the_original_password():
    hashed = hash_password("correct-password")
    assert hashed.startswith("$2")  # formato bcrypt
    assert verify_password("correct-password", hashed)
    assert not verify_password("Correct-password", hashed)


def test_same_password_produces_different_hashes():
    # La sal aleatoria impide comparar hashes para descubrir contraseñas iguales.
    assert hash_password("same-password") != hash_password("same-password")


@pytest.mark.parametrize(
    ("password", "too_long"),
    [("a" * 72, False), ("ñ" * 36, False), ("a" * 73, True), ("ñ" * 37, True)],
    ids=["72-ascii", "72-bytes-utf8", "73-ascii", "74-bytes-utf8"],
)
def test_bcrypt_limit_is_measured_in_bytes(password, too_long):
    assert exceeds_bcrypt_limit(password) is too_long


def test_overlong_password_never_matches_instead_of_crashing():
    hashed = hash_password("a" * 72)
    assert verify_password("a" * 73, hashed) is False


@pytest.mark.parametrize(
    "build",
    [
        lambda pw: UserUpdate(password=pw),
        lambda pw: ResetPasswordRequest(token="t", new_password=pw),
        lambda pw: ChangePasswordRequest(current_password="x", new_password=pw),
    ],
    ids=["editar-usuario", "reset", "cambio"],
)
def test_every_new_password_entry_point_enforces_the_byte_limit(build):
    with pytest.raises(ValidationError):
        build("ñ" * 40)
