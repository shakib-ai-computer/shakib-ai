"""Per-user long-term memory items (user-visible and deletable).

All operations are scoped to the authenticated user; other users' items
are invisible and return 404 on delete.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MemoryItem, User
from app.security import get_current_user

router = APIRouter()


class MemoryCreate(BaseModel):
    kind: str = Field(default="note", max_length=100)
    content: str = Field(min_length=1)


def _item_dict(item: MemoryItem) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "content": item.content,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.post("/", status_code=201)
def create_item(
    body: MemoryCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = MemoryItem(user_id=user.id, kind=body.kind, content=body.content)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_dict(item)


@router.get("/")
def list_items(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    items = (
        db.query(MemoryItem)
        .filter(MemoryItem.user_id == user.id)
        .order_by(MemoryItem.id)
        .all()
    )
    return {"items": [_item_dict(i) for i in items]}


@router.delete("/{item_id}", status_code=204)
def delete_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(MemoryItem)
        .filter(MemoryItem.id == item_id, MemoryItem.user_id == user.id)
        .one_or_none()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="memory item not found")
    db.delete(item)
    db.commit()
    return None
