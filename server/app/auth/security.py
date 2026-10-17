# from pwdlib import PasswordHash
# from jose import jwt,JWTError
# from datetime import datetime, timedelta, timezone
# password_hash = PasswordHash.recommended()

# def hash_password(password: str) -> str:
#     return password_hash.hash(password)

# def verify_password(password: str, hashed_password: str) -> bool:
#     return password_hash.verify(password,hashed_password)
##************************************** old  agron hashing changed due to mismatch  with  eralier hashing (bycript)

import os
import uuid

from pwdlib.hashers.bcrypt import BcryptHasher
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone

password_hash = BcryptHasher()

# bcrypt reads at most 72 BYTES and silently discards the rest. Two passwords
# sharing their first 72 bytes therefore hash identically and both verify.
#
# pwdlib has no option to refuse this, so the cap is enforced here, at the
# one place every caller goes through. The request schemas apply the same
# limit to turn an over-long password into a 422; this is the backstop for
# any path that reaches the hasher without passing through them.
#
# Measured in bytes, not characters: one multi-byte character can consume
# several of the 72. Single definition on purpose -- this constant and its
# message were previously copied into two schemas, which is how they drift.
BCRYPT_MAX_BYTES = 72


def password_too_long_error(length: int) -> ValueError:
    return ValueError(
        f"Password must be at most {BCRYPT_MAX_BYTES} bytes; this one is "
        f"{length}."
    )


def check_password_bytes(value):
    """Raise if bcrypt would silently truncate this password.

    Accepts None because UserUpdate.password is optional and its validator
    still runs when the field is absent.
    """
    if value is None:
        return value
    length = len(value.encode("utf-8"))
    if length > BCRYPT_MAX_BYTES:
        raise password_too_long_error(length)
    return value


def hash_password(password: str) -> str:
    return password_hash.hash(check_password_bytes(password))


def verify_password(password: str, hashed_password: str) -> bool:
    # Fails rather than raises: an over-long password cannot match any stored
    # hash, and login must never turn an impossible credential into a 500.
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        return False
    return password_hash.verify(password, hashed_password)
#*************************************************************************
# Secret key used to sign the JWT. Read from the environment so it is never
# hardcoded in source; falls back to the previous development value only if
# JWT_SECRET_KEY is not set, so existing local setups keep working until
# they add it to .env.
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "temporary-secret-key")
ALGORITHM = "HS256" #algorithm

def _base_claims(data: dict) -> dict:
    """Claims common to every token kind.

    exp/iat/jti are always overwritten so a caller cannot smuggle them in,
    and jti makes each token unique. Without it, two logins in the same
    second were byte-identical, because sub, token_gen and exp are all
    second-granular.
    """
    to_encode = data.copy()
    for key in ("exp", "iat", "jti", "type"):
        to_encode.pop(key, None)
    return to_encode


def create_access_token(
    data: dict,
    expires_minutes: int = 30
) -> str:

    now = datetime.now(timezone.utc)
    to_encode = _base_claims(data)

    to_encode["iat"] = int(now.timestamp())
    to_encode["exp"] = int((now + timedelta(minutes=expires_minutes)).timestamp())
    to_encode["jti"] = uuid.uuid4().hex
    to_encode["type"] = "access"

    return jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

def decode_access_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM]
    )
    if payload.get("type") != "access":
        raise JWTError("Invalid access token")


    return payload

def create_refresh_token(
    data: dict,
    expires_days: int = 7
) -> str:

    now = datetime.now(timezone.utc)
    to_encode = _base_claims(data)

    to_encode["iat"] = int(now.timestamp())
    to_encode["exp"] = int((now + timedelta(days=expires_days)).timestamp())
    to_encode["jti"] = uuid.uuid4().hex
    to_encode["type"] = "refresh"

    return jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

def decode_refresh_token(token:str) -> dict:
    payload = jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM]
    )

    if payload.get("type") != "refresh":
        raise JWTError("Invalid refresh token")

    return payload


# Media tokens let an <img>/<video> fetch a file. A media element cannot
# send an Authorization header, so without this the gallery is broken: the
# browser requests the content URL with no credentials and gets a 401.
#
# Deliberately narrow and short-lived:
#   * "media" type, so it can never be used as an access token;
#   * a 5 minute life, so a leaked URL stops working almost immediately;
#   * it grants nothing on its own. The route still checks the user and the
#     project, and the token only stands in for the missing header.
MEDIA_TOKEN_TTL_MINUTES = 5


def create_media_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "type": "media",
            "iat": int(now.timestamp()),
            "exp": int(
                (now + timedelta(minutes=MEDIA_TOKEN_TTL_MINUTES)).timestamp()
            ),
            "jti": uuid.uuid4().hex,
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_media_token(token: str) -> int:
    """Return the user id carried by a media token.

    Raises JWTError when the token is malformed, expired, or is an access or
    refresh token being passed off as a media token.
    """
    payload = jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM]
    )

    if payload.get("type") != "media":
        raise JWTError("Invalid media token")

    return int(payload["sub"])