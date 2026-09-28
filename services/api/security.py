import os
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from services.api.auth_models import User
from services.api.user_service import get_user_by_id


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
ALGORITHM = "HS256"


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales no válidas",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _secret_key() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY no está configurada")
    return secret


def _expiration_minutes() -> int:
    try:
        minutes = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    except ValueError as error:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES debe ser un entero") from error
    if minutes <= 0:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES debe ser mayor que cero")
    return minutes


def create_access_token(
    user_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    expires_at = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=_expiration_minutes())
    )
    return jwt.encode(
        {"sub": user_id, "exp": expires_at},
        _secret_key(),
        algorithm=ALGORITHM,
    )


def create_reset_token(user_id: str) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "purpose": "password-reset",
            "jti": str(uuid4()),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        },
        _secret_key(),
        algorithm=ALGORITHM,
    )


def reset_token_user_id(token: str) -> str | None:
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
    except (JWTError, RuntimeError):
        return None
    if payload.get("purpose") != "password-reset":
        return None
    user_id = payload.get("sub")
    return user_id if isinstance(user_id, str) else None


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not isinstance(user_id, str) or payload.get("purpose") is not None:
            raise _unauthorized()
    except (JWTError, RuntimeError) as error:
        raise _unauthorized() from error

    user = get_user_by_id(user_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    return user