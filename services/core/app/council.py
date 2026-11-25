"""Critical Thinking Council — four adversarial review passes over a
research report and its evidence set (architecture plan §3, item 7).

The four members are independent LLM calls, each with a distinct system
prompt and a strict JSON output schema:

- ``devils_advocate`` — the strongest counter-arguments to the report's
  main conclusions.
- ``autopsy`` — the weakest reasoning steps, thinnest evidence and
  unsupported leaps.
- ``red_team`` — how the conclusion could be wrong, manipulated or gamed,
  including adversarial scenarios.
- ``expose`` — what is missing: unexamined angles, one-sided sourcing,
  undisclosed limitations.

Honesty rules baked in:

- The council output is a SEPARATE analysis object. It is stored next to
  the research run as ``council.json`` and returned to the caller — the
  report itself is never read for writing, never modified, never merged.
- If the gateway is not configured, :meth:`CouncilService.analyze` raises
  :class:`CouncilNotConfigured` — it never fabricates a review.
- If a member's reply is not valid strict JSON matching its schema, that
  member is retried exactly once; if it still fails, that member's section
  is ``{"status": "error", ...}`` while the other members still return
  their real output. A member's output is never invented.
- If the gateway call itself fails for a member (after the role fallback),
  that member's section is likewise an honest ``error`` section.

Model roles: the ``strategic`` role is preferred (this is judgement work),
with the ``smart`` role as fallback when the strategic chain is
unconfigured or fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.gateway import GatewayClient, GatewayError, GatewayNotConfigured
from app.research.service import DEFAULT_REPORTS_DIR, ResearchService

# Preferred role first; the next is tried when a role's chain is empty or
# every model in it fails.
ROLE_PREFERENCE = ("strategic", "smart")

MEMBER_ORDER = ("devils_advocate", "autopsy", "red_team", "expose")

_MEMBER_SPECS: dict[str, dict[str, Any]] = {
    "devils_advocate": {
        "title": "Devil's Advocate",
        "mission": (
            "Your job is to argue AGAINST the report. Build the strongest "
            "possible counter-arguments to its main conclusions — attack "
            "the claims themselves, not the writing style."
        ),
        "list_key": "points",
        "item_keys": ("point", "target_claim", "strength"),
        "shape": (
            '{"member": "devils_advocate", "summary": "<one-paragraph '
            'overview of the case against the report>", "points": '
            '[{"point": "<counter-argument>", "target_claim": "<the '
            'report claim it attacks>", "strength": '
            '"low|medium|high"}]}'
        ),
    },
    "autopsy": {
        "title": "Autopsy",
        "mission": (
            "Your job is to dissect the report's reasoning. Find the "
            "weakest reasoning steps, the places where the evidence is "
            "thinnest, and any unsupported leaps from evidence to "
            "conclusion."
        ),
        "list_key": "findings",
        "item_keys": ("issue", "severity", "evidence_gap"),
        "shape": (
            '{"member": "autopsy", "summary": "<one-paragraph overview '
            'of the reasoning health of the report>", "findings": '
            '[{"issue": "<weak reasoning step>", "severity": '
            '"low|medium|high", "evidence_gap": "<what evidence is '
            'missing or thin>"}]}'
        ),
    },
    "red_team": {
        "title": "Red Team",
        "mission": (
            "Your job is adversarial: work out how the report's "
            "conclusions could be wrong, manipulated or gamed — including "
            "bad-faith actors, poisoned or planted sources, incentives to "
            "deceive, and scenarios where acting on the conclusion causes "
            "harm."
        ),
        "list_key": "scenarios",
        "item_keys": ("scenario", "plausibility", "impact"),
        "shape": (
            '{"member": "red_team", "summary": "<one-paragraph overview '
            'of the adversarial risk>", "scenarios": [{"scenario": '
            '"<how the conclusion could be wrong or gamed>", '
            '"plausibility": "low|medium|high", "impact": "<what '
            'happens if this scenario is true>"}]}'
        ),
    },
    "expose": {
        "title": "Expose",
        "mission": (
            "Your job is to surface what the report does NOT say: "
            "unexamined angles, one-sided sourcing, missing perspectives "
            "or stakeholders, and limitations the report itself does not "
            "disclose."
        ),
        "list_key": "gaps",
        "item_keys": ("gap", "why_it_matters"),
        "shape": (
            '{"member": "expose", "summary": "<one-paragraph overview '
            'of what the report leaves out>", "gaps": [{"gap": "<what '
            'is missing or one-sided>", "why_it_matters": "<why the '
            'omission matters>"}]}'
        ),
    },
}


class CouncilNotConfigured(Exception):
    """The model gateway is not configured; the council cannot run."""


class CouncilError(Exception):
    """A council run failed in a way that is not a member-level error."""


def _parse_model_json(content: str) -> Any:
    """Parse a model reply as JSON, tolerating a surrounding code fence."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    return json.loads(text)


def _system_prompt(member: str, language: str) -> str:
    spec = _MEMBER_SPECS[member]
    prompt = (
        f"You are the {spec['title']}, one member of a Critical Thinking "
        "Council reviewing a research report and the sources it used. "
        + spec["mission"]
        + " Be specific: refer to the report's actual claims and its "
        "source list, not generic advice. Respond with JSON only, exactly "
        f"in this shape: {spec['shape']}. Do not add any text outside "
        "the JSON object."
    )
    if language == "bn":
        prompt += (
            " Write every text value in Bengali (বাংলা); keep the JSON "
            'keys and the "member" value in English.'
        )
    return prompt


def _user_prompt(report_markdown: str, sources: list[dict]) -> str:
    lines = []
    for i, source in enumerate(sources or [], start=1):
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or source.get("url") or "").strip()
        url = str(source.get("url") or "").strip()
        line = f"{i}. {title} — {url}" if url else f"{i}. {title}"
        score = source.get("credibility_score")
        if isinstance(score, (int, float)):
            line += f" (credibility score: {score}/100)"
        lines.append(line)
    sources_text = "\n".join(lines) if lines else "(no source list provided)"
    return (
        "Research report (Markdown):\n\n"
        f"{report_markdown}\n\n"
        f"Sources used by the report:\n{sources_text}"
    )


def _validate_member_payload(member: str, parsed: Any) -> dict:
    """Validate a parsed member reply against the member's strict schema.

    Returns the normalised section content (without ``status``). Raises
    ValueError on any structural mismatch — the caller treats that as a
    parse failure and retries once.
    """
    spec = _MEMBER_SPECS[member]
    if not isinstance(parsed, dict):
        raise ValueError("reply is not a JSON object")
    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("reply has no non-empty 'summary'")
    raw_items = parsed.get(spec["list_key"])
    if not isinstance(raw_items, list):
        raise ValueError(f"reply's {spec['list_key']!r} is not a list")
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError(f"a {spec['list_key']} entry is not an object")
        item = {}
        for key in spec["item_keys"]:
            if key not in raw:
                raise ValueError(f"a {spec['list_key']} entry is missing {key!r}")
            item[key] = str(raw[key])
        items.append(item)
    return {"member": member, "summary": summary, spec["list_key"]: items}


class CouncilService:
    """Runs the four council members over a report via the gateway."""

    def __init__(
        self,
        *,
        gateway: Any = None,
        reports_dir: Path | None = None,
    ):
        # ``gateway`` is a GatewayClient (or a test double with the same
        # surface: a ``configured`` flag and an async ``chat_completion``).
        self._gateway = gateway if gateway is not None else GatewayClient()
        self._reports_dir = Path(reports_dir) if reports_dir else DEFAULT_REPORTS_DIR
        self._research = ResearchService(reports_dir=self._reports_dir)

    @property
    def configured(self) -> bool:
        return bool(getattr(self._gateway, "configured", False))

    @property
    def reports_dir(self) -> Path:
        return self._reports_dir

    def load_run(self, run_id: str) -> dict | None:
        """Stored research run artifacts, or None if the id is unknown."""
        return self._research.load_run(run_id)

    async def _call_model(self, messages: list[dict]) -> tuple[str, str]:
        """One model call, strategic role preferred, smart as fallback.

        Returns (reply_text, role_used). Raises GatewayError when every
        preferred role failed; GatewayNotConfigured propagates so the
        caller can surface the not-configured state distinctly.
        """
        errors: list[str] = []
        for role in ROLE_PREFERENCE:
            try:
                response = await self._gateway.chat_completion(
                    role, messages, temperature=0
                )
                return response["choices"][0]["message"]["content"], role
            except GatewayNotConfigured:
                raise
            except GatewayError as exc:
                errors.append(f"{role}: {exc}")
            except (KeyError, IndexError, TypeError) as exc:
                errors.append(f"{role}: malformed gateway response ({exc.__class__.__name__})")
        raise GatewayError(
            "council model call failed for all roles: " + "; ".join(errors)
        )

    async def _run_member(
        self,
        member: str,
        report_markdown: str,
        sources: list[dict],
        language: str,
    ) -> tuple[dict, str | None]:
        """Run one council member; returns (section, role_used_or_None).

        A member whose reply is not valid schema JSON is retried once.
        A member that still fails gets an honest ``error`` section — its
        output is never fabricated.
        """
        messages = [
            {"role": "system", "content": _system_prompt(member, language)},
            {"role": "user", "content": _user_prompt(report_markdown, sources)},
        ]
        last_parse_error: Exception | None = None
        for _attempt in range(2):  # initial try + exactly one retry
            try:
                content, role = await self._call_model(messages)
            except GatewayNotConfigured:
                raise
            except GatewayError as exc:
                return (
                    {
                        "member": member,
                        "status": "error",
                        "reason": f"gateway call failed: {exc}",
                    },
                    None,
                )
            try:
                payload = _validate_member_payload(member, _parse_model_json(content))
            except ValueError as exc:
                last_parse_error = exc
                continue
            return {"status": "ok", **payload}, role
        return (
            {
                "member": member,
                "status": "error",
                "reason": "model reply was not valid strict JSON matching "
                f"the member schema after 2 attempts ({last_parse_error})",
            },
            None,
        )

    async def analyze(
        self,
        report_markdown: str,
        sources: list[dict],
        language: str = "en",
        run_id: str | None = None,
    ) -> dict:
        """Run all four council members over a report.

        Returns ``{run_id?, language, members, generated_by_role}``. When
        ``run_id`` names a stored research run, the result is also written
        to ``council.json`` in that run's directory. The report itself is
        never modified — the council output lives alongside it.

        Raises CouncilNotConfigured when the gateway is not configured and
        CouncilError for an invalid/unknown ``run_id``.
        """
        if not self.configured:
            raise CouncilNotConfigured(
                "model gateway not configured; the Critical Thinking "
                "Council needs the gateway's 'strategic' (or 'smart') "
                "model role — set GATEWAY_BASE_URL and GATEWAY_API_KEY "
                "on the server"
            )
        if language not in ("en", "bn"):
            raise CouncilError(f"unsupported language {language!r}; use 'en' or 'bn'")
        run_dir: Path | None = None
        if run_id is not None:
            if not run_id or Path(run_id).name != run_id:
                raise CouncilError(f"invalid run_id {run_id!r}")
            run_dir = self._reports_dir / run_id
            if not run_dir.is_dir():
                raise CouncilError(f"unknown research run {run_id!r}")

        members: dict[str, dict] = {}
        generated_by_role: str | None = None
        try:
            for member in MEMBER_ORDER:
                section, role = await self._run_member(
                    member, report_markdown, sources, language
                )
                members[member] = section
                if generated_by_role is None and role is not None:
                    generated_by_role = role
        except GatewayNotConfigured as exc:
            raise CouncilNotConfigured(str(exc)) from exc

        result: dict[str, Any] = {
            "language": language,
            "members": members,
            "generated_by_role": generated_by_role,
        }
        if run_id is not None:
            result = {"run_id": run_id, **result}
            assert run_dir is not None
            (run_dir / "council.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return result
