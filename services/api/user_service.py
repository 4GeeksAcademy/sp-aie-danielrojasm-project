from datetime import datetime, timezone
from uuid import uuid4

from tinydb import Query

from services.api.auth_models import Profile, ProfileFields, User, UserCreate, UserUpdate
from services.api.database import get_auth_db
from services.api.passwords import hash_password


class EmailAlreadyExistsError(ValueError):
    pass


def _user_from_document(document: dict[str, object] | None) -> User | None:
    return User.model_validate(document) if document is not None else None


def _profile_from_document(document: dict[str, object] | None) -> Profile | None:
    return Profile.model_validate(document) if document is not None else None


def create_user(payload: UserCreate) -> tuple[User, Profile]:
    normalized_email = str(payload.email).lower()
    user_id = str(uuid4())
    profile_id = str(uuid4())
    user_document = {
        "id": user_id,
        "email": normalized_email,
        "hashed_password": hash_password(payload.password),
        "is_active": True,
        "role": "user",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    profile_document = {
        "id": profile_id,
        "user_id": user_id,
        "name": payload.name,
        "phone": payload.phone,
        "address": payload.address,
    }

    with get_auth_db() as db:
        users = db.table("users")
        profiles = db.table("profiles")
        if users.contains(Query().email == normalized_email):
            raise EmailAlreadyExistsError(normalized_email)
        users.insert(user_document)
        try:
            profiles.insert(profile_document)
        except Exception:
            users.remove(Query().id == user_id)
            raise

    return User.model_validate(user_document), Profile.model_validate(profile_document)


def get_user_by_id(user_id: str) -> User | None:
    with get_auth_db() as db:
        document = db.table("users").get(Query().id == user_id)
    return _user_from_document(document)


def get_user_by_email(email: str) -> User | None:
    normalized_email = email.lower()
    with get_auth_db() as db:
        document = db.table("users").get(Query().email == normalized_email)
    return _user_from_document(document)


def list_users() -> list[User]:
    with get_auth_db() as db:
        documents = db.table("users").all()
    return [User.model_validate(document) for document in documents]


def update_user(user_id: str, payload: UserUpdate) -> User | None:
    updates = payload.model_dump(exclude_none=True)
    password = updates.pop("password", None)
    if password is not None:
        updates["hashed_password"] = hash_password(password)
    if "email" in updates:
        normalized_email = str(updates["email"]).lower()
        with get_auth_db() as db:
            existing = db.table("users").get(Query().email == normalized_email)
        if existing is not None and existing["id"] != user_id:
            raise EmailAlreadyExistsError(normalized_email)
        updates["email"] = normalized_email
    if "role" in updates and payload.role is not None:
        updates["role"] = payload.role.value

    with get_auth_db() as db:
        users = db.table("users")
        if users.get(Query().id == user_id) is None:
            return None
        if updates:
            users.update(updates, Query().id == user_id)
        document = users.get(Query().id == user_id)
    return _user_from_document(document)


def delete_user(user_id: str) -> bool:
    with get_auth_db() as db:
        users = db.table("users")
        if users.get(Query().id == user_id) is None:
            return False
        users.remove(Query().id == user_id)
        db.table("profiles").remove(Query().user_id == user_id)
    return True


def get_profile_by_user_id(user_id: str) -> Profile | None:
    with get_auth_db() as db:
        document = db.table("profiles").get(Query().user_id == user_id)
    return _profile_from_document(document)


def update_profile(user_id: str, payload: ProfileFields) -> Profile | None:
    with get_auth_db() as db:
        profiles = db.table("profiles")
        if profiles.get(Query().user_id == user_id) is None:
            return None
        profiles.update(payload.model_dump(), Query().user_id == user_id)
        document = profiles.get(Query().user_id == user_id)
    return _profile_from_document(document)