"""GET /auth/me y GET/PUT /profiles/me — datos de la sesión actual."""

import pytest
from fastapi import HTTPException
from tinydb import Query

from services.api.auth_models import ProfileUpdate
from services.api.database import get_auth_db
from services.api.routes.auth import auth_me
from services.api.routes.profiles import get_my_profile, put_my_profile


def remove_profile(user_id: str) -> None:
    with get_auth_db() as db:
        db.table("profiles").remove(Query().user_id == user_id)


# --- Camino feliz -----------------------------------------------------------

def test_me_returns_email_role_and_profile(make_user):
    user = make_user(name="Valentina Cruz", address="Zaragoza")

    me = auth_me(user).model_dump()

    assert me["id"] == user.id
    assert me["email"] == "ana@example.com"  # /auth/me sí devuelve el email propio
    assert me["role"] == "user"
    # El perfil sale sin sus claves internas (`id`, `user_id`) y nunca sale el hash.
    assert me["profile"] == {"name": "Valentina Cruz", "phone": None, "address": "Zaragoza"}
    assert "hashed_password" not in me


def test_profile_can_be_updated(make_user):
    user = make_user()
    updated = put_my_profile(ProfileUpdate(name="Ana", phone="+34 600 000 000"), user)
    assert (updated.name, updated.phone) == ("Ana", "+34 600 000 000")
    assert get_my_profile(user).name == "Ana"


# --- Casos límite -----------------------------------------------------------

def test_profile_without_optional_data(make_user):
    user = make_user()
    profile = get_my_profile(user)
    assert (profile.name, profile.phone, profile.address) == (None, None, None)


def test_put_replaces_the_whole_profile(make_user):
    # PUT es un reemplazo: un campo omitido se vacía. El formulario del
    # backoffice siempre envía los tres campos, así que es el comportamiento
    # esperado; el test lo fija para que un cambio a PATCH sea deliberado.
    user = make_user(name="Ana", phone="+1 555 0100")
    updated = put_my_profile(ProfileUpdate(name="Ana"), user)
    assert updated.phone is None


# --- Modos de fallo ---------------------------------------------------------

def test_me_fails_when_profile_is_missing(make_user):
    user = make_user()
    remove_profile(user.id)
    with pytest.raises(HTTPException) as error:
        auth_me(user)
    assert error.value.status_code == 404


def test_profile_endpoints_fail_when_profile_is_missing(make_user):
    user = make_user()
    remove_profile(user.id)
    for call in (lambda: get_my_profile(user), lambda: put_my_profile(ProfileUpdate(), user)):
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 404
