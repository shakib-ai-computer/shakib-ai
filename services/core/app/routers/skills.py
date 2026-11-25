"""Skills & tools registry: SHAKIB AI's built-in capabilities and their
live readiness.

Statuses are computed from the same configuration flags the feature
endpoints themselves check (``settings.gateway_configured`` /
``settings.research_configured``), so this registry cannot claim a
capability is ready while its endpoint would answer 503:

- ``ready`` — usable now.
- ``needs_configuration`` — implemented, but server configuration is
  missing; ``missing`` names exactly what (env var names, never values).
- ``client_side`` — runs in the browser, no server component.
"""

from fastapi import APIRouter

from app.config import settings

router = APIRouter()


def _gateway_missing() -> list[str]:
    missing = []
    if not settings.gateway_base_url.strip():
        missing.append("GATEWAY_BASE_URL")
    if not settings.gateway_api_key.strip():
        missing.append("GATEWAY_API_KEY")
    return missing


def _gateway_status() -> dict:
    if settings.gateway_configured:
        return {"status": "ready", "missing": []}
    return {"status": "needs_configuration", "missing": _gateway_missing()}


def _registry() -> list[dict]:
    gateway = _gateway_status()
    if settings.research_configured:
        research = {"status": "ready", "missing": []}
    else:
        research = {
            "status": "needs_configuration",
            "missing": settings.research_missing(),
        }
    return [
        {
            "name": "deep_research",
            "description": "Multi-agent deep research with citations, "
            "credibility-scored sources and a contradiction check "
            "(gpt-researcher via the model gateway).",
            **research,
        },
        {
            "name": "critical_council",
            "description": "Critical Thinking Council — Devil's Advocate, "
            "Autopsy, Red Team and Expose passes over a research report.",
            **gateway,
        },
        {
            "name": "file_reader",
            "description": "Upload PDF, DOCX, TXT or Markdown files (max "
            "20 MB) and read their extracted text.",
            "status": "ready",
            "missing": [],
        },
        {
            "name": "image_generation",
            "description": "Generate images through the model gateway "
            "(/v1/images/generations).",
            **gateway,
        },
        {
            "name": "long_term_memory",
            "description": "Per-user long-term memory items, stored in the "
            "Core database and visible/deletable by their owner.",
            "status": "ready",
            "missing": [],
        },
        {
            "name": "voice",
            "description": "Voice assistant using the browser's built-in "
            "speech recognition and synthesis — no server component.",
            "status": "client_side",
            "missing": [],
        },
    ]


@router.get("/")
def list_skills() -> dict:
    return {"skills": _registry()}
