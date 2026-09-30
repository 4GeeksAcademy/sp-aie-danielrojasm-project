from fastapi import APIRouter, Depends, HTTPException

from services.api.auth_models import ProfileRead, ProfileUpdate, User
from services.api.security import get_current_user
from services.api.user_service import get_profile_by_user_id, update_profile


router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/me", response_model=ProfileRead)
def get_my_profile(current_user: User = Depends(get_current_user)) -> ProfileRead:
    profile = get_profile_by_user_id(current_user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return ProfileRead.model_validate(profile)


@router.put("/me", response_model=ProfileRead)
def put_my_profile(
    payload: ProfileUpdate,
    current_user: User = Depends(get_current_user),
) -> ProfileRead:
    profile = update_profile(current_user.id, payload)
    if profile is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return profile