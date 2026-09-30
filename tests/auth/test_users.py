"""GET/PUT/DELETE /users — permisos y reglas del CRUD de credenciales."""

import pytest
from fastapi import HTTPException

from services.api.auth_models import UserRole, UserUpdate
from services.api.database import get_auth_db
from services.api.passwords import verify_password
from services.api.routes.users import get_user, get_users, put_user, remove_user
from services.api.user_service import (
    get_profile_by_user_id,
    get_user_by_id,
    issue_reset_token,
)


def status_of(call, *args) -> int:
    with pytest.raises(HTTPException) as error:
        call(*args)
    return error.value.status_code


# --- Camino feliz -----------------------------------------------------------

def test_owner_reads_and_updates_own_account(make_user):
    user = make_user()

    assert get_user(user.id, user).email == "ana@example.com"
    updated = put_user(user.id, UserUpdate(email="Ana.W@Example.com"), user)

    assert updated.email == "ana.w@example.com"


def test_admin_lists_users_and_changes_roles(make_user):
    admin = make_user(email="kim@example.com", role=UserRole.ADMIN)
    staff = make_user(email="carlos@example.com")

    assert {item.email for item in get_users(admin)} == {"kim@example.com", "carlos@example.com"}
    assert put_user(staff.id, UserUpdate(role=UserRole.MANAGER), admin).role == "manager"


def test_owner_deletes_account_with_profile_and_pending_resets(make_user):
    user = make_user()
    issue_reset_token(user.id)

    remove_user(user.id, user)

    assert get_user_by_id(user.id) is None
    assert get_profile_by_user_id(user.id) is None
    with get_auth_db() as db:
        # Sin tokens huérfanos que pudieran reactivar la cuenta.
        assert db.table("password_resets").all() == []


# --- Casos límite -----------------------------------------------------------

def test_changing_own_email_case_is_not_a_duplicate(make_user):
    user = make_user()
    assert put_user(user.id, UserUpdate(email="ANA@example.com"), user).email == "ana@example.com"


def test_changing_password_invalidates_pending_reset_links(make_user):
    user = make_user()
    issue_reset_token(user.id)

    updated = put_user(user.id, UserUpdate(password="brand-new-password"), user)

    assert "hashed_password" not in updated.model_dump()  # el hash nunca sale
    assert verify_password("brand-new-password", get_user_by_id(user.id).hashed_password)
    with get_auth_db() as db:
        assert db.table("password_resets").all() == []


def test_empty_update_leaves_account_unchanged(make_user):
    user = make_user()
    assert put_user(user.id, UserUpdate(), user).model_dump() == user.model_dump(
        exclude={"hashed_password"}
    )
    assert get_user_by_id(user.id) == user


# --- Modos de fallo ---------------------------------------------------------

def test_regular_user_cannot_list_users(make_user):
    assert status_of(get_users, make_user()) == 403


def test_regular_user_cannot_touch_another_account(make_user):
    ana = make_user()
    carlos = make_user(email="carlos@example.com")

    assert status_of(get_user, carlos.id, ana) == 403
    assert status_of(put_user, carlos.id, UserUpdate(email="x@example.com"), ana) == 403
    assert status_of(remove_user, carlos.id, ana) == 403
    assert get_user_by_id(carlos.id) is not None  # nada se modificó


@pytest.mark.parametrize(
    "change",
    [UserUpdate(role=UserRole.ADMIN), UserUpdate(is_active=False)],
    ids=["rol", "estado"],
)
def test_regular_user_cannot_change_own_role_or_status(make_user, change):
    user = make_user()
    assert status_of(put_user, user.id, change, user) == 403
    assert get_user_by_id(user.id).role == "user"


def test_email_already_used_by_another_account_is_rejected(make_user):
    ana = make_user()
    make_user(email="carlos@example.com")
    assert status_of(put_user, ana.id, UserUpdate(email="CARLOS@example.com"), ana) == 409


def test_admin_gets_404_for_unknown_user(make_user):
    admin = make_user(role=UserRole.ADMIN)
    assert status_of(get_user, "missing-id", admin) == 404
    assert status_of(put_user, "missing-id", UserUpdate(email="x@example.com"), admin) == 404
    assert status_of(remove_user, "missing-id", admin) == 404
