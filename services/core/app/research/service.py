"""ResearchService — gpt-researcher embedded as a library, pointed at the
new-api gateway.

Configuration mapping (gpt-researcher reads its config from environment
variables when a researcher is constructed):

- ``OPENAI_BASE_URL`` = GATEWAY_BASE_URL + "/v1"  (the gateway is
  OpenAI-compatible, so gpt-researcher's native OpenAI provider talks to it)
- ``OPENAI_API_KEY``  = GATEWAY_API_KEY (server-side only, never logged)
- ``FAST_LLM`` / ``SMART_LLM`` / ``STRATEGIC_LLM`` = "openai:" + the FIRST
  model of the matching MODEL_* fallback chain (gpt-researcher takes a
  single model per role; chain-level fallback stays a gateway concern)
- ``EMBEDDING`` = "openai:" + first MODEL_EMBEDDING model, when configured
- ``RETRIEVER`` / ``TAVILY_API_KEY`` from settings

Language: gpt-researcher has no universally supported ``language``
constructor argument across versions, so when the installed version accepts
one it is used; otherwise, for Bengali runs, an explicit instruction is
appended to the query (the documented prompt-level route) and meta.json
records which mechanism was used — never silently assumed.

The gpt-researcher import is LAZY: this module imports fine without the
package installed, and only an actual run requires it.
"""

from __future__ import annotations

import inspect
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from app.config import Settings, settings as default_settings

DEFAULT_REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"

BENGALI_INSTRUCTION = (
    "\n\nIMPORTANT: Write the entire final report in Bengali (বাংলা), "
    "including headings. Keep source titles and URLs unchanged."
)


class ResearchNotConfigured(Exception):
    """Research prerequisites are missing; ``missing`` names them."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(
            "research not configured; missing server env: " + ", ".join(missing)
        )


class ResearchError(Exception):
    """A research run failed (engine missing, gateway error, ...)."""


def _first(chain: list[str]) -> str:
    return chain[0] if chain else ""


def researcher_env(s: Settings) -> dict[str, str]:
    """Environment gpt-researcher needs, derived from SHAKIB AI settings."""
    base = s.gateway_base_url.strip().rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    env = {
        "OPENAI_BASE_URL": base,
        "OPENAI_API_KEY": s.gateway_api_key,
        "RETRIEVER": s.retriever.strip() or "tavily",
    }
    if s.tavily_api_key.strip():
        env["TAVILY_API_KEY"] = s.tavily_api_key
    for role, var in (
        ("fast", "FAST_LLM"),
        ("smart", "SMART_LLM"),
        ("strategic", "STRATEGIC_LLM"),
    ):
        model = _first(s.model_chain(role))
        if model:
            env[var] = f"openai:{model}"
    embedding = _first(s.model_chain("embedding"))
    if embedding:
        env["EMBEDDING"] = f"openai:{embedding}"
    return env


@contextmanager
def _applied_env(env: dict[str, str]) -> Iterator[None]:
    """Temporarily set env vars (gpt-researcher reads them at construction).

    Previous values are restored afterwards. Note: concurrent runs share
    process env — acceptable while runs are request-scoped and configured
    identically; revisit if per-run configs ever diverge.
    """
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _load_researcher_class() -> type:
    try:
        from gpt_researcher import GPTResearcher
    except ImportError as exc:
        raise ResearchError(
            "the 'gpt-researcher' package is not installed in the Core "
            "environment; research runs are unavailable until it is"
        ) from exc
    return GPTResearcher


def _normalise_sources(raw: Any) -> list[dict]:
    sources: list[dict] = []
    seen: set[str] = set()
    for item in raw or []:
        if isinstance(item, dict):
            url = str(item.get("url") or item.get("href") or "").strip()
            title = str(item.get("title") or url).strip()
        else:
            url = str(item).strip()
            title = url
        if url and url not in seen:
            seen.add(url)
            sources.append({"url": url, "title": title})
    return sources


class ResearchService:
    def __init__(
        self,
        *,
        settings_obj: Settings | None = None,
        reports_dir: Path | None = None,
        researcher_factory: Callable[..., Any] | None = None,
    ):
        self._settings = settings_obj or default_settings
        self._reports_dir = Path(reports_dir) if reports_dir else DEFAULT_REPORTS_DIR
        self._factory = researcher_factory

    @property
    def configured(self) -> bool:
        return self._settings.research_configured

    def missing(self) -> list[str]:
        return self._settings.research_missing()

    @property
    def reports_dir(self) -> Path:
        return self._reports_dir

    def _build_researcher(self, query: str, report_type: str, language: str):
        """Construct a GPTResearcher; returns (researcher, language_note)."""
        factory = self._factory or _load_researcher_class()
        kwargs: dict[str, Any] = {"query": query, "report_type": report_type}
        language_note = "report language: default (query language)"
        if language == "bn":
            params = inspect.signature(factory).parameters
            if "language" in params:
                kwargs["language"] = "bn"
                language_note = "Bengali requested via researcher's language parameter"
            else:
                kwargs["query"] = query + BENGALI_INSTRUCTION
                language_note = (
                    "Bengali requested via instruction appended to the query "
                    "(installed gpt-researcher exposes no language parameter)"
                )
        return factory(**kwargs), language_note

    async def run(
        self,
        query: str,
        language: str = "en",
        report_type: str = "research_report",
    ) -> dict:
        """Run one deep-research job and store its artifacts on disk.

        Returns {run_id, report_markdown, sources, costs, meta}. Raises
        ResearchNotConfigured / ResearchError — never fabricates a report.
        """
        if not self.configured:
            raise ResearchNotConfigured(self.missing())
        env = researcher_env(self._settings)
        with _applied_env(env):
            researcher, language_note = self._build_researcher(
                query, report_type, language
            )
            await researcher.conduct_research()
            report = await researcher.write_report()
        raw_sources = []
        if hasattr(researcher, "get_research_sources"):
            raw_sources = researcher.get_research_sources() or []
        if not raw_sources and hasattr(researcher, "visited_urls"):
            raw_sources = list(researcher.visited_urls or [])
        sources = _normalise_sources(raw_sources)
        costs = None
        if hasattr(researcher, "get_costs"):
            try:
                costs = researcher.get_costs()
            except Exception:  # cost reporting is best-effort only
                costs = None

        run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        meta = {
            "run_id": run_id,
            "query": query,
            "language": language,
            "report_type": report_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "retriever": env.get("RETRIEVER"),
            "models": {
                var: env[var]
                for var in ("FAST_LLM", "SMART_LLM", "STRATEGIC_LLM")
                if var in env
            },
            "language_handling": language_note,
            "costs": costs,
            "source_count": len(sources),
        }
        run_dir = self._reports_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "report.md").write_text(report or "", encoding="utf-8")
        (run_dir / "sources.json").write_text(
            json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (run_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            "run_id": run_id,
            "report_markdown": report or "",
            "sources": sources,
            "costs": costs,
            "meta": meta,
        }

    def load_run(self, run_id: str) -> dict | None:
        """Stored artifacts for a run, or None if the run id is unknown."""
        if not run_id or Path(run_id).name != run_id:
            return None  # refuse path traversal via run ids
        run_dir = self._reports_dir / run_id
        report_path = run_dir / "report.md"
        if not report_path.is_file():
            return None
        sources: list[dict] = []
        meta: dict = {}
        sources_path = run_dir / "sources.json"
        if sources_path.is_file():
            sources = json.loads(sources_path.read_text(encoding="utf-8"))
        meta_path = run_dir / "meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return {
            "run_id": run_id,
            "report_markdown": report_path.read_text(encoding="utf-8"),
            "sources": sources,
            "meta": meta,
        }
