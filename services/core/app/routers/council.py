"""Critical Thinking Council endpoints: Devil's Advocate, Autopsy,
Red Team and Expose passes over a research report plus its evidence set.

The council output is a SEPARATE analysis (stored as ``council.json``
next to the research run when one is named) — it is never merged into
or written over the report.

Honesty contract:

- POST returns **503** while the model gateway is not configured —
  never a fabricated review.
- An unknown ``run_id`` returns **404**.
- A member whose model reply is not valid strict JSON is retried once,
  then reported as an ``error`` section inside an otherwise successful
  response — never silently invented.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.council import CouncilError, CouncilNotConfigured, CouncilService
from app.models import User
from app.security import get_current_user_if_required

router = APIRouter()


def get_council_service() -> CouncilService:
    """Dependency seam — tests substitute a fake-gateway service here."""
    return CouncilService()


class CouncilRequest(BaseModel):
    # Either identify a stored research run ...
    run_id: str | None = None
    # ... or provide the report and its sources inline.
    report_markdown: str | None = None
    sources: list[dict] = Field(default_factory=list)
    language: Literal["en", "bn"] = "en"


@router.post("/")
async def run_council(
    req: CouncilRequest,
    service: CouncilService = Depends(get_council_service),
    # Enforced only when AUTH_REQUIRED=true (see app/security.py).
    _user: User | None = Depends(get_current_user_if_required),
) -> dict:
    run_id: str | None = None
    if req.run_id:
        run = service.load_run(req.run_id)
        if run is None:
            raise HTTPException(
                status_code=404, detail=f"unknown research run {req.run_id!r}"
            )
        report_markdown = run["report_markdown"]
        sources = run["sources"]
        run_id = req.run_id
    elif req.report_markdown:
        report_markdown = req.report_markdown
        sources = req.sources
    else:
        raise HTTPException(
            status_code=422,
            detail="provide either 'run_id' or 'report_markdown'",
        )
    try:
        return await service.analyze(
            report_markdown, sources, language=req.language, run_id=run_id
        )
    except CouncilNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CouncilError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
