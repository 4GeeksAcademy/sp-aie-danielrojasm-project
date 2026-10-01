"""Fixtures comunes: cada test usa bases de datos TinyDB temporales y un entorno
controlado, de modo que nunca toca `services/api/*.json` ni depende del `.env`."""

from collections.abc import Callable
from typing import Any

import pytest

from services.api.auth_models import User, UserCreate, UserRole, UserUpdate
from services.api.routes.incidents import summary_cache
from services.api.routes.inventory import products_cache
from services.api.routes.telemetry_report import report_cache
from services.api.user_service import create_user, update_user
from tests.helpers import DEFAULT_PASSWORD, TEST_SECRET


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.json"))
    monkeypatch.setenv("SUPPLIERS_DB_PATH", str(tmp_path / "suppliers.json"))
    monkeypatch.setenv("INCIDENTS_DB_PATH", str(tmp_path / "incidents.json"))
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    # Variables del Codespace o del .env que cambiarían el comportamiento.
    for variable in (
        "DATABASE_URL",
        "RESEND_API_KEY",
        "RESEND_FROM_EMAIL",
        "PASSWORD_RESET_URL",
        "CODESPACE_NAME",
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN",
    ):
        monkeypatch.delenv(variable, raising=False)
    # Las cachés son del módulo: sin vaciarlas, un test vería el resumen o el
    # stock de la base temporal del test anterior.
    products_cache.invalidate("test")
    summary_cache.invalidate("test")
    report_cache.invalidate("test")


@pytest.fixture
def make_user() -> Callable[..., User]:
    """Crea un usuario real mediante `user_service`, opcionalmente con otro rol."""

    def _make(
        email: str = "ana@example.com",
        password: str = DEFAULT_PASSWORD,
        role: UserRole | None = None,
        **profile: Any,
    ) -> User:
        user, _ = create_user(UserCreate(email=email, password=password, **profile))
        if role is not None:
            updated = update_user(user.id, UserUpdate(role=role))
            assert updated is not None
            user = updated
        return user

    return _make
