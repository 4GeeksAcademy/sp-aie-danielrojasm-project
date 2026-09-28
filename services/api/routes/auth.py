from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from services.api.auth_models import CurrentUserResponse, LoginRequest, TokenResponse, User
from services.api.passwords import verify_password
from services.api.security import create_access_token, get_current_user
from services.api.user_service import get_profile_by_user_id, get_user_by_email


router = APIRouter(prefix="/auth", tags=["auth"])


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