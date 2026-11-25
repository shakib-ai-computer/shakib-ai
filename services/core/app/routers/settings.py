"""API and model settings: gateway model roles, provider status.

Keys stay server-side; this router never returns key values.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User, UserApiKey
from app.security import encrypt_secret, get_current_user

router = APIRouter()


@router.get("/")
def status():
    raise HTTPException(status_code=501, detail="settings module not implemented yet (scaffold)")


# ------------------------------------------------------- user provider keys
class KeyCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=1)


def _key_dict(row: UserApiKey) -> dict:
    """Public view of a stored key: NEVER includes the key itself."""
    return {
        "id": row.id,
        "provider": row.provider,
        "last4": row.last4,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/keys", status_code=201)
def store_key(
    body: KeyCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Store a user-supplied provider key, Fernet-encrypted at rest.

    One row per (user, provider): storing again replaces the old key.
    The plaintext is used only to compute the ciphertext and last4.
    """
    provider = body.provider.strip().lower()
    existing = (
        db.query(UserApiKey)
        .filter(UserApiKey.user_id == user.id, UserApiKey.provider == provider)
        .one_or_none()
    )
    if existing is not None:
        db.delete(existing)
        db.flush()
    row = UserApiKey(
        user_id=user.id,
        provider=provider,
        encrypted_key=encrypt_secret(body.api_key),
        last4=body.api_key[-4:],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _key_dict(row)


@router.get("/keys")
def list_keys(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    rows = (
        db.query(UserApiKey)
        .filter(UserApiKey.user_id == user.id)
        .order_by(UserApiKey.id)
        .all()
    )
    return {"keys": [_key_dict(r) for r in rows]}


@router.delete("/keys/{provider}", status_code=204)
def delete_key(
    provider: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(UserApiKey)
        .filter(
            UserApiKey.user_id == user.id,
            UserApiKey.provider == provider.strip().lower(),
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="no key stored for that provider")
    db.delete(row)
    db.commit()
    return None


@router.get("/models")
def model_settings() -> dict:
    """Configured model-role fallback chains (names only — never secrets)."""
    return {
        "gateway_configured": settings.gateway_configured,
        "gateway_base_url": settings.gateway_base_url,
        "roles": settings.model_roles,
    }
