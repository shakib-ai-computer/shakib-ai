"""Per-user conversation history.

Every query is scoped to the authenticated user. Asking for another
user's conversation returns 404 (not 403) so its existence is not leaked.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Conversation, Message, User
from app.security import get_current_user

router = APIRouter()


class ConversationCreate(BaseModel):
    title: str = Field(default="", max_length=500)


class MessageCreate(BaseModel):
    role: str = Field(min_length=1, max_length=50)
    content: str


def _conversation_dict(conv: Conversation) -> dict:
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }


def _message_dict(msg: Message) -> dict:
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "role": msg.role,
        "content": msg.content,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def _own_conversation(db: Session, user: User, conversation_id: int) -> Conversation:
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .one_or_none()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.post("/", status_code=201)
def create_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = Conversation(user_id=user.id, title=body.title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return _conversation_dict(conv)


@router.get("/")
def list_conversations(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.id.desc())
        .all()
    )
    return {"conversations": [_conversation_dict(c) for c in convs]}


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = _own_conversation(db, user, conversation_id)
    result = _conversation_dict(conv)
    result["messages"] = [_message_dict(m) for m in conv.messages]
    return result


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = _own_conversation(db, user, conversation_id)
    db.delete(conv)
    db.commit()
    return None


@router.post("/{conversation_id}/messages", status_code=201)
def add_message(
    conversation_id: int,
    body: MessageCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = _own_conversation(db, user, conversation_id)
    msg = Message(conversation_id=conv.id, role=body.role, content=body.content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return _message_dict(msg)


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = _own_conversation(db, user, conversation_id)
    return {"messages": [_message_dict(m) for m in conv.messages]}
