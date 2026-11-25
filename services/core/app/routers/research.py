"""Deep research endpoints: gpt-researcher (via ResearchService) with
credibility-scored sources, a contradiction check, and MD/DOCX/PDF export.

Honesty contract:

- POST returns **503** naming exactly which server env is missing while
  research is not configured — never a fabricated report.
- The contradiction check reports its own status (ok / skipped / error);
  a skipped check is surfaced, not hidden.
- Export returns **503** with the reason when a format is unavailable in
  this environment (e.g. PDF without WeasyPrint or a Bengali font).
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.gateway import GatewayClient
from app.research import exports
from app.research.contradiction import check_contradictions
from app.research.credibility import score_sources
from app.research.service import (
    ResearchError,
    ResearchNotConfigured,
    ResearchService,
)
from app.models import User
from app.routers.chat import get_gateway_client
from app.security import get_current_user_if_required

router = APIRouter()


def get_research_service() -> ResearchService:
    """Dependency seam — tests substitute a mock-backed service here."""
    return ResearchService()


class ResearchRequest(BaseModel):
    query: str = Field(min_length=3)
    language: Literal["en", "bn"] = "en"
    report_type: str = "research_report"


@router.post("/")
async def run_research(
    req: ResearchRequest,
    service: ResearchService = Depends(get_research_service),
    gateway: GatewayClient = Depends(get_gateway_client),
    # Enforced only when AUTH_REQUIRED=true (see app/security.py).
    _user: User | None = Depends(get_current_user_if_required),
) -> dict:
    if not service.configured:
        raise HTTPException(
            status_code=503,
            detail="research not configured; missing server env: "
            + ", ".join(service.missing()),
        )
    try:
        result = await service.run(
            req.query, language=req.language, report_type=req.report_type
        )
    except ResearchNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ResearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    scored_sources = score_sources(result["sources"])
    contradiction = await check_contradictions(
        result["report_markdown"], scored_sources, gateway
    )
    return {
        "run_id": result["run_id"],
        "report_markdown": result["report_markdown"],
        "sources": scored_sources,
        "contradiction": contradiction,
        "costs": result["costs"],
        "meta": result["meta"],
    }


@router.get("/{run_id}/export")
def export_run(
    run_id: str,
    format: Literal["md", "docx", "pdf"] = Query(default="md"),
    service: ResearchService = Depends(get_research_service),
):
    run = service.load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown research run {run_id!r}")
    out_path = service.reports_dir / run_id / f"export.{format}"
    try:
        exports.EXPORTERS[format](run["report_markdown"], run["sources"], out_path)
    except exports.ExportUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(
        out_path,
        media_type=exports.MEDIA_TYPES[format],
        filename=f"shakib-ai-research-{run_id}.{format}",
    )
