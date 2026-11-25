"""SHAKIB AI Core configuration.

All settings come from environment variables (see repo-root .env.example).
API keys default to EMPTY — they are never hard-coded and never sent to the
frontend. An empty key means the corresponding integration is not configured
yet, and the app must say so honestly instead of pretending to work.
"""

from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Model gateway (new-api). Core is the ONLY component that holds this key.
    gateway_base_url: str = "http://localhost:3000/v1"
    gateway_api_key: str = ""

    # Model roles -> gateway model names. Each value is a comma-separated
    # FALLBACK CHAIN: models are tried in order until one succeeds
    # (e.g. MODEL_SMART="model-a,model-b"). Empty = role not configured.
    model_fast: str = ""
    model_smart: str = ""
    model_strategic: str = ""
    model_embedding: str = ""

    # Data stores. Dev default is a local SQLite file; production sets
    # DATABASE_URL to PostgreSQL (docker-compose does this for the core
    # service).
    database_url: str = "sqlite:///./data/shakib.db"
    redis_url: str = "redis://localhost:6379/0"

    # SHAKIB AI's own auth
    jwt_secret: str = ""
    # When True, chat/research/council endpoints require a valid JWT.
    # Default False keeps local dev and the public demo usable without an
    # account; production deployments should set AUTH_REQUIRED=true.
    auth_required: bool = False
    # Browser origins allowed by CORS (comma-separated). Dev default covers
    # the Vite dev server only. PRODUCTION MUST set CORS_ORIGINS to the
    # exact deployed origin(s) — never "*" (credentials are involved).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Fernet key (urlsafe base64, 32 bytes) for encrypting user-supplied
    # provider API keys at rest. If unset, a key is DERIVED from JWT_SECRET
    # (see app/security.py) — that is a dev convenience only: production
    # MUST set ENCRYPTION_KEY explicitly so rotating the JWT secret does
    # not silently make stored keys undecryptable.
    encryption_key: str = ""

    # Web research (server-side only). RETRIEVER names a gpt-researcher
    # retriever; the default "tavily" needs TAVILY_API_KEY. Key-free
    # retrievers (see KEY_FREE_RETRIEVERS) work without any key, at lower
    # quality — they are never presented as equivalent to Tavily.
    retriever: str = "tavily"
    tavily_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed CORS_ORIGINS (empty entries dropped)."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def gateway_configured(self) -> bool:
        return bool(self.gateway_base_url.strip() and self.gateway_api_key.strip())

    def model_chain(self, role: str) -> list[str]:
        """Ordered fallback chain for a role (empty list if unset/unknown)."""
        raw = getattr(self, f"model_{role}", "")
        return [name.strip() for name in raw.split(",") if name.strip()]

    @property
    def model_roles(self) -> dict[str, list[str]]:
        """All known roles mapped to their configured fallback chains."""
        return {
            role: self.model_chain(role)
            for role in ("fast", "smart", "strategic", "embedding")
        }

    # gpt-researcher retrievers that need no API key.
    KEY_FREE_RETRIEVERS: ClassVar[frozenset] = frozenset(
        {"duckduckgo", "arxiv", "openalex"}
    )

    @property
    def retriever_key_free(self) -> bool:
        return self.retriever.strip().lower() in self.KEY_FREE_RETRIEVERS

    @property
    def research_configured(self) -> bool:
        """Research needs the model gateway AND a usable retriever."""
        return bool(
            self.gateway_configured
            and (self.tavily_api_key.strip() or self.retriever_key_free)
        )

    def research_missing(self) -> list[str]:
        """Human-readable list of what research still needs (no secrets)."""
        missing: list[str] = []
        if not self.gateway_base_url.strip():
            missing.append("GATEWAY_BASE_URL")
        if not self.gateway_api_key.strip():
            missing.append("GATEWAY_API_KEY")
        if not (self.tavily_api_key.strip() or self.retriever_key_free):
            missing.append(
                "TAVILY_API_KEY (or set RETRIEVER to a key-free retriever: "
                + ", ".join(sorted(self.KEY_FREE_RETRIEVERS))
                + ")"
            )
        return missing


settings = Settings()
