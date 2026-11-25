"""User authentication: register / login / me.

Passwords are bcrypt-hashed (app/security.py); sessions are 24h JWTs.
Duplicate registration returns 409; bad credentials return 401 without
revealing which part was wrong.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User
from app.security import authenticate_user, create_access_token, get_current_user, hash_password

router = APIRouter()


class Credentials(BaseModel):
    # EmailStr needs the email-validator package; a plain str keeps the
    # dependency footprint small — format is lightly checked in register.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user), user_id=user.id, email=user.email
    )


@router.post("/register", status_code=201, response_model=TokenResponse)
def register(creds: Credentials, db: Session = Depends(get_db)) -> TokenResponse:
    # Atomicity guard: registration ends by issuing a JWT, which is
    # impossible without JWT_SECRET. Check BEFORE writing anything so a
    # misconfigured server answers 503 with NO side effects — previously
    # the user row was committed first and the caller was left with a
    # registered account but no token (and a retry then hit 409).
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=503,
            detail="auth not configured on the server: JWT_SECRET is not set",
        )
    email = creds.email.strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="invalid email address")
    if db.query(User).filter(User.email == email).one_or_none() is not None:
        raise HTTPException(status_code=409, detail="email already registered")
    user = User(email=email, password_hash=hash_password(creds.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # race on the unique constraint
        db.rollback()
        raise HTTPException(status_code=409, detail="email already registered")
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(creds: Credentials, db: Session = Depends(get_db)) -> TokenResponse:
    user = authenticate_user(db, creds.email.strip().lower(), creds.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    return _token_response(user)


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "user_id": user.id,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
