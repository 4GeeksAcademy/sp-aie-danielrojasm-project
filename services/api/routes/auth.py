import logging
import os
from typing import Any
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from services.api.auth_models import (
    ChangePasswordRequest, CurrentUserResponse, ForgotPasswordRequest,
    LoginRequest, ResetPasswordRequest, TokenResponse, User,
)
from services.api.passwords import verify_password
from services.api.reset_email import EmailDeliveryError, send_reset_email
from services.api.security import create_access_token, get_current_user
from services.api.user_service import (
    change_user_password, get_profile_by_user_id, get_user_by_email,
    issue_reset_token, reset_user_password,
)


router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _reset_url() -> str:
    configured = os.getenv("PASSWORD_RESET_URL", "http://localhost:3002/reset-password")
    url = urlparse(configured)
    codespace = os.getenv("CODESPACE_NAME")
    domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
    if url.hostname in ("localhost", "127.0.0.1") and codespace and domain:
        return url._replace(
            scheme="https", netloc=f"{codespace}-{url.port or 3002}.{domain}"
        ).geturl()
    return configured


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest) -> dict[str, str]:
    user = get_user_by_email(str(payload.email))
    if user is not None and user.is_active:
        token = issue_reset_token(user.id)
        base_url = _reset_url()
        link = f"{base_url}?token={quote(token, safe='')}"
        try:
            send_reset_email(user.email, link)
        except EmailDeliveryError as error:
            # La respuesta sigue siendo genérica para no revelar si la cuenta
            # existe; el log no incluye el email, el enlace ni el token.
            logger.error("No se pudo enviar el restablecimiento de contraseña: %s", error)
    return {"message": "Si esa dirección está registrada, recibirás un enlace en breve"}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest) -> dict[str, str]:
    if not reset_user_password(payload.token, payload.new_password):
        raise HTTPException(status_code=400, detail="Enlace inválido, caducado o ya utilizado")
    return {"message": "Contraseña actualizada"}


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest, current_user: User = Depends(get_current_user)
) -> dict[str, str]:
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")
    change_user_password(current_user.id, payload.new_password)
    return {"message": "Contraseña actualizada"}


async def _login_payload(request: Request) -> LoginRequest:
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            return LoginRequest.model_validate(await request.json())
        form = await request.form()
        return LoginRequest.model_validate(
            {
                "email": form.get("email") or form.get("username"),
                "password": form.get("password"),
            }
        )
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Email y contraseña son obligatorios") from error


@router.post(
    "/login",
    response_model=TokenResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string", "format": "email"},
                            "password": {"type": "string", "format": "password"},
                        },
                        "required": ["email", "password"],
                    }
                },
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "username": {"type": "string", "format": "email"},
                            "password": {"type": "string", "format": "password"},
                        },
                        "required": ["username", "password"],
                    }
                },
            },
        }
    },
)
async def login(request: Request) -> TokenResponse:
    payload = await _login_payload(request)
    user = get_user_by_email(str(payload.email))
    if user is None or not user.is_active or not verify_password(
        payload.password, user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=CurrentUserResponse)
def auth_me(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    profile = get_profile_by_user_id(current_user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return {
        "email": current_user.email,
        "role": current_user.role,
        "profile": profile,
    }