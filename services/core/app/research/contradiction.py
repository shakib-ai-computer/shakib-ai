"""Claim-level contradiction check for research reports.

Pipeline: extract a small set of key claims from the report with simple,
deterministic sentence heuristics, then ask the gateway's *smart* model —
with a strict JSON-only prompt — whether any two claims directly contradict
each other.

Honesty rules baked in:

- If the gateway is not configured, the check returns
  ``{"status": "skipped", "reason": ...}`` — it never pretends to have run.
- If the model's reply is not valid JSON, the check returns
  ``{"status": "error", ...}`` rather than guessing.
- A "no contradictions found" result means the model saw none among the
  extracted claims; it is not a proof that the report is consistent.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.gateway import GatewayError

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKUP_RE = re.compile(r"[#>*`_~]+")

_SYSTEM_PROMPT = (
    "You are a strict fact-consistency checker. You will receive a numbered "
    "list of claims extracted from one research report. Identify pairs of "
    "claims that DIRECTLY contradict each other (they cannot both be true). "
    "Do not flag claims that are merely about different aspects, different "
    "time periods, or different scopes. Respond with JSON only, exactly in "
    'this shape: {"contradictions": [{"claim_a": <index>, "claim_b": '
    '<index>, "explanation": "<one sentence>"}]}. If there are no direct '
    "contradictions, respond with {\"contradictions\": []}."
)


def _clean(markdown: str) -> str:
    text = _LINK_RE.sub(r"\1", markdown or "")
    text = _MARKUP_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_claims(report_markdown: str, max_claims: int = 8) -> list[str]:
    """Up to ``max_claims`` key claims, chosen by transparent heuristics.

    Candidate sentences must be 40-300 characters with at least six words.
    Sentences containing figures (digits / percentages) rank first — numeric
    claims are the ones that most often contradict — then longer sentences.
    Selection is deterministic; returned claims keep report order.
    """
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(_clean(report_markdown))]
    candidates: list[tuple[int, int, int, str]] = []
    for idx, sentence in enumerate(sentences):
        if not (40 <= len(sentence) <= 300):
            continue
        if len(sentence.split()) < 6:
            continue
        has_figure = 1 if re.search(r"\d", sentence) else 0
        candidates.append((idx, has_figure, len(sentence), sentence))
    # Rank: figures first, then length; keep the original indices so the
    # chosen claims can be restored to report order.
    ranked = sorted(candidates, key=lambda c: (-c[1], -c[2], c[0]))
    chosen = sorted(ranked[:max_claims], key=lambda c: c[0])
    return [c[3] for c in chosen]


def _parse_model_json(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    return json.loads(text)


async def check_contradictions(
    report_markdown: str,
    sources: list[dict],
    gateway: Any,
    max_claims: int = 8,
) -> dict:
    """Check the report's key claims for pairwise contradictions.

    ``gateway`` is a GatewayClient (or a test double with the same surface:
    a ``configured`` flag and an async ``chat_completion``). ``sources`` is
    accepted for interface completeness — the current check works on the
    report text itself.
    """
    if gateway is None or not getattr(gateway, "configured", False):
        return {
            "status": "skipped",
            "reason": "model gateway not configured; the contradiction "
            "check needs the gateway's 'smart' model role",
        }
    claims = extract_claims(report_markdown, max_claims=max_claims)
    if len(claims) < 2:
        return {
            "status": "skipped",
            "reason": f"only {len(claims)} extractable claim(s) in the "
            "report; at least two are needed for a pairwise check",
            "claims_checked": len(claims),
        }
    numbered = "\n".join(f"{i}. {claim}" for i, claim in enumerate(claims))
    try:
        response = await gateway.chat_completion(
            "smart",
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Claims:\n{numbered}"},
            ],
            temperature=0,
        )
    except GatewayError as exc:
        return {"status": "error", "reason": str(exc), "claims_checked": len(claims)}
    try:
        content = response["choices"][0]["message"]["content"]
        parsed = _parse_model_json(content)
        raw_pairs = parsed["contradictions"]
        if not isinstance(raw_pairs, list):
            raise ValueError("'contradictions' is not a list")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return {
            "status": "error",
            "reason": f"model reply was not valid strict JSON ({exc.__class__.__name__})",
            "claims_checked": len(claims),
        }
    contradictions = []
    for pair in raw_pairs:
        try:
            a, b = int(pair["claim_a"]), int(pair["claim_b"])
            if not (0 <= a < len(claims) and 0 <= b < len(claims)) or a == b:
                continue
            contradictions.append(
                {
                    "claim_a": claims[a],
                    "claim_b": claims[b],
                    "explanation": str(pair.get("explanation", "")),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return {
        "status": "ok",
        "claims_checked": len(claims),
        "contradictions": contradictions,
    }
