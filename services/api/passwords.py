from passlib.hash import bcrypt


# bcrypt solo admite 72 bytes; con acentos o "ñ" se llega antes que a 72 caracteres.
MAX_PASSWORD_BYTES = 72


def exceeds_bcrypt_limit(password: str) -> bool:
    return len(password.encode("utf-8")) > MAX_PASSWORD_BYTES


def hash_password(password: str) -> str:
    return bcrypt.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    # Ningún hash guardado puede proceder de una contraseña más larga que el
    # límite, así que es simplemente incorrecta (y bcrypt lanzaría ValueError).
    if exceeds_bcrypt_limit(password):
        return False
    return bcrypt.verify(password, hashed_password)
