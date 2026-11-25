"""SHAKIB AI Core — FastAPI application.

The app boots, /health reports real status, and feature routers are
registered: chat, research, council, files (upload + text extraction),
images, skills, memory, conversations, settings and auth. Anything not
implemented yet returns an honest 501; auth, conversations, memory, user
key storage and uploaded documents are backed by the database configured
in DATABASE_URL.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.routers import (
    auth,
    chat,
    conversations,
    council,
    files,
    images,
    memory,
    research,
    settings as settings_router,
    skills,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="SHAKIB AI Core", version="0.2.0", lifespan=lifespan)

# Browser access: the web app is served from a different origin than Core
# in dev (Vite :5173 -> Core :8000) and in production. Origins come from
# CORS_ORIGINS (see app/config.py) — an explicit allowlist, never "*",
# because requests carry the Authorization header.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(research.router, prefix="/api/research", tags=["research"])
app.include_router(council.router, prefix="/api/council", tags=["council"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(images.router, prefix="/api/images", tags=["images"])
app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
app.include_router(
    conversations.router, prefix="/api/conversations", tags=["conversations"]
)
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])


@app.get("/health")
def health() -> dict:
    """Service status. Reports configuration presence, never key values."""
    return {
        "status": "ok",
        "service": "shakib-ai-core",
        "version": app.version,
        "gateway_configured": settings.gateway_configured,
        "research_configured": settings.research_configured,
        "auth_required": settings.auth_required,
    }
