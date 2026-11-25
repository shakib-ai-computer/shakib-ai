"""File and PDF reader: uploads, text extraction, document listing.

Uploads are allowlisted (.pdf/.txt/.md/.docx), capped at 20 MB, stored
under data/uploads/<scope>/<id>, and their text is extracted at upload
time (see app/files_service.py). Documents are scoped: a signed-in user
sees only their own documents, anonymous callers see only the anonymous
scope, and any other scope's document answers 404 — its existence is not
leaked. Auth is optional (same pattern as chat): when AUTH_REQUIRED is on,
a valid token is required; see app.security.get_optional_user.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import files_service
from app.db import get_db
from app.models import Document, User
from app.security import get_optional_user

router = APIRouter()


def _meta_dict(doc: Document) -> dict:
    return {
        "id": doc.id,
        "filename": doc.filename,
        "mime": doc.mime,
        "size": doc.size,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


def _scoped_query(db: Session, user: User | None):
    """Documents visible to this caller: their own, or the anon scope."""
    return db.query(Document).filter(Document.user_id == (user.id if user else None))


def _get_own_document(db: Session, user: User | None, doc_id: int) -> Document:
    doc = _scoped_query(db, user).filter(Document.id == doc_id).one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return doc


@router.post("/upload", status_code=201)
async def upload(
    file: UploadFile = File(...),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    mime = files_service.ALLOWED_TYPES.get(extension)
    if mime is None:
        allowed = ", ".join(sorted(files_service.ALLOWED_TYPES))
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file type {extension or '(none)'}; allowed: {allowed}",
        )

    # Read with a hard cap: stop as soon as the limit is exceeded instead
    # of buffering an unbounded upload.
    limit = files_service.MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"file too large; maximum upload size is {limit} bytes",
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    try:
        text = files_service.extract_text(extension, data)
    except files_service.ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    doc = Document(
        user_id=user.id if user else None,
        filename=filename,
        mime=mime,
        size=len(data),
        text=text,
    )
    db.add(doc)
    db.flush()  # assigns doc.id, needed for the on-disk path
    files_service.write_bytes(doc.user_id, doc.id, data)
    db.commit()
    db.refresh(doc)
    return {**_meta_dict(doc), "text_chars": len(text)}


@router.get("/")
def list_documents(
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    docs = _scoped_query(db, user).order_by(Document.id).all()
    return {"documents": [_meta_dict(d) for d in docs]}


@router.get("/{doc_id}")
def get_document(
    doc_id: int,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    doc = _get_own_document(db, user, doc_id)
    limit = files_service.TEXT_PREVIEW_LIMIT
    return {
        **_meta_dict(doc),
        "text": doc.text[:limit],
        "truncated": len(doc.text) > limit,
    }


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: int,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    doc = _get_own_document(db, user, doc_id)
    files_service.delete_bytes(doc.user_id, doc.id)
    db.delete(doc)
    db.commit()
    return None
