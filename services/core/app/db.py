"""Database engine/session wiring (SQLAlchemy 2.x).

The engine is built from ``settings.database_url``. Dev default is a local
SQLite file; production sets DATABASE_URL to PostgreSQL via compose.
Tests override DATABASE_URL before importing the app and call
:func:`reset_engine` to rebuild against the temp database.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings


def _make_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def reset_engine(url: str | None = None) -> None:
    """Rebuild the global engine/session factory (used by tests)."""
    global engine, SessionLocal
    engine.dispose()
    engine = _make_engine(url or settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables if they do not exist yet."""
    from app import models  # noqa: F401  (register models on Base)

    models.Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
