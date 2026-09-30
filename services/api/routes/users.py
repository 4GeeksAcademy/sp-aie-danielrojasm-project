from fastapi import APIRouter, Depends, HTTPException, Response, status

from services.api.auth_models import (
    User,
    UserCreate,
    UserListItem,
    UserRead,
    UserRegistered,
    UserRole,
    UserUpdate,
)
from services.api.security import get_current_user
from services.api.user_service import (
    EmailAlreadyExistsError,
    create_user,
    delete_user,
    get_user_by_id,
    list_users,
    update_user,
)


router = APIRouter(prefix="/users", tags=["users"])


def _ensure_owner_or_admin(user_id: str, current_user: User) -> None:
    if current_user.id != user_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="No tienes permiso para este usuario")


def _ensure_admin(current_user: User) -> None:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Solo un admin puede listar usuarios")


@router.post("", response_model=UserRegistered, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate) -> UserRegistered:
    try:
        user, _ = create_user(payload)
    except EmailAlreadyExistsError as error:
        raise HTTPException(status_code=409, detail="El email ya está registrado") from error
    # El cliente ya conoce el email (lo acaba de enviar): no se reenvía.
    return UserRegistered.model_validate(user)


@router.get("", response_model=list[UserListItem])
def get_users(current_user: User = Depends(get_current_user)) -> list[UserListItem]:
    _ensure_admin(current_user)
    return [UserListItem.model_validate(user) for user in list_users()]


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: str, current_user: User = Depends(get_current_user)) -> UserRead:
    _ensure_owner_or_admin(user_id, current_user)
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return UserRead.model_validate(user)


@router.put("/{user_id}", response_model=UserRead)
def put_user(
    user_id: str,
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
) -> UserRead:
    _ensure_owner_or_admin(user_id, current_user)
    if (
        payload.role is not None or payload.is_active is not None
    ) and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Solo un admin puede cambiar rol o estado")
    try:
        user = update_user(user_id, payload)
    except EmailAlreadyExistsError as error:
        raise HTTPException(status_code=409, detail="El email ya está registrado") from error
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return UserRead.model_validate(user)


# 204 sin cuerpo: no hay payload que serializar, así que se declara
# explícitamente que la ruta no tiene response_model.
@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def remove_user(user_id: str, current_user: User = Depends(get_current_user)) -> None:
    _ensure_owner_or_admin(user_id, current_user)
    if not delete_user(user_id):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")