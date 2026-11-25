"""Authentication & secret-handling primitives.

- Passwords: bcrypt hashes (never stored or logged in plaintext).
- Sessions: JWT access tokens (HS256, PyJWT), 24h expiry, signed with
  JWT_SECRET from settings.
- User-supplied provider API keys: Fernet (AES-128-CBC + HMAC) ciphertext
  at rest. The Fernet key comes from ENCRYPTION_KEY; if that is unset it
  is DERIVED from JWT_SECRET (SHA-256 -> urlsafe base64). Derivation is a
  DEV convenience only — production must set ENCRYPTION_KEY explicitly,
  because rotating JWT_SECRET would otherwise orphan every stored key.
"""

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

TOKEN_TTL = timedelta(hours=24)
_bearer = HTTPBearer(auto_error=False)

# Throwaway hash used to keep login timing uniform for unknown emails.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode()


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    # bcrypt operates on at most 72 bytes; truncate explicitly so long
    # passwords behave deterministically instead of erroring.
    raw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:72], password_hash.encode()
        )
    except ValueError:
        return False


# --------------------------------------------------------------------- JWT
def _jwt_secret() -> str:
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=503,
            detail="auth not configured on the server: JWT_SECRET is not set",
        )
    return settings.jwt_secret


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now,
        "exp": now + TOKEN_TTL,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ------------------------------------------------------------ dependencies
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Require a valid Bearer JWT; 401 on missing/invalid token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decode_token(credentials.credentials)
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token subject no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user_if_required(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """For feature routers: enforce auth only when AUTH_REQUIRED is on.

    When the setting is off the request proceeds anonymously (returns
    None); when on, this behaves exactly like :func:`get_current_user`.
    """
    if not settings.auth_required:
        return None
    return get_current_user(credentials, db)


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """Resolve the caller for endpoints that scope data per user but also
    work anonymously (file uploads).

    - No token: anonymous (returns None) — unless AUTH_REQUIRED is on, in
      which case this behaves exactly like :func:`get_current_user`.
    - A token is present: it must be valid. A bad token is a 401, never a
      silent downgrade to anonymous, so a signed-in user can never
      accidentally write into (or read from) the anonymous scope.
    """
    if credentials is None:
        if settings.auth_required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None
    payload = _decode_token(credentials.credentials)
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token subject no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None:
        verify_password(password, _DUMMY_HASH)  # uniform timing
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


# ------------------------------------------------- provider-key encryption
def _fernet() -> Fernet:
    if settings.encryption_key:
        key = settings.encryption_key.encode()
    else:
        # DEV ONLY fallback: derive from JWT_SECRET (see module docstring).
        digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
