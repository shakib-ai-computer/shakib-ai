"""Deterministic source-credibility scoring (heuristics, NOT truth checks).

Each source gets a 0-100 score from transparent, reproducible signals:

- **Source type** inferred from the domain: government (.gov) and academic
  (.edu / .ac.*, known scholarly publishers) score highest; established news
  outlets get a modest bonus; self-published blog platforms a small penalty;
  forums and social media a larger one.
- **Transport**: HTTPS is a small positive signal, plain HTTP a small
  negative one.
- **Corroboration**: if other sources on *independent* domains have titles
  covering similar significant tokens, the source gains points — independent
  agreement is a real (if weak) credibility signal.

Honesty note: these are surface heuristics. A high score does NOT mean the
content is true, and a low score does NOT mean it is false — the score only
summarises where a source sits and how well it is corroborated, so a human
(or a downstream module) can prioritise what to read first. The function is
pure and deterministic: same input, same output, no network, no LLM.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

BASE_SCORE = 50

# Curated domain signals. Kept small and explicit on purpose: an auditable
# list beats a clever model here.
ACADEMIC_PUBLISHERS = frozenset({
    "arxiv.org", "nature.com", "science.org", "sciencedirect.com",
    "springer.com", "link.springer.com", "ieee.org", "dl.acm.org",
    "acm.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
    "jstor.org", "onlinelibrary.wiley.com", "plos.org", "oup.com",
    "academic.oup.com", "cambridge.org", "tandfonline.com",
})
ESTABLISHED_NEWS = frozenset({
    "bbc.com", "bbc.co.uk", "reuters.com", "apnews.com", "nytimes.com",
    "theguardian.com", "aljazeera.com", "washingtonpost.com", "wsj.com",
    "economist.com", "ft.com", "npr.org", "prothomalo.com",
    "thedailystar.net", "bdnews24.com", "dhakatribune.com",
    "banglatribune.com", "ittefaq.com.bd", "jugantor.com",
})
BLOG_PLATFORMS = frozenset({
    "medium.com", "substack.com", "wordpress.com", "blogspot.com",
    "blogger.com", "dev.to", "hashnode.dev", "ghost.io",
})
FORUM_SOCIAL = frozenset({
    "reddit.com", "facebook.com", "twitter.com", "x.com", "quora.com",
    "youtube.com", "tiktok.com", "linkedin.com", "pinterest.com",
})

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "by", "at", "from", "as", "it", "its",
    "this", "that", "how", "what", "why", "when", "who",
})

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _host(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return (parsed.hostname or "").lower()


def _registered(host: str) -> str:
    """Last two labels of a host (good enough for the curated lists)."""
    parts = [p for p in host.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _title_tokens(title: str) -> frozenset[str]:
    return frozenset(
        tok
        for tok in _TOKEN_RE.findall((title or "").lower())
        if len(tok) >= 3 and tok not in _STOPWORDS
    )


def _type_signal(host: str) -> tuple[int, str | None]:
    """(points, reason) for the domain's source-type signal."""
    reg = _registered(host)
    labels = host.split(".")
    if "gov" in labels:
        return 25, "government domain (.gov)"
    if "edu" in labels or "ac" in labels:
        return 25, "academic institution domain (.edu/.ac)"
    if host in ACADEMIC_PUBLISHERS or reg in ACADEMIC_PUBLISHERS:
        return 25, "scholarly publisher / academic archive"
    if host in ESTABLISHED_NEWS or reg in ESTABLISHED_NEWS:
        return 10, "established news outlet"
    if host in BLOG_PLATFORMS or reg in BLOG_PLATFORMS:
        return -10, "self-published blog platform"
    if host in FORUM_SOCIAL or reg in FORUM_SOCIAL:
        return -20, "forum / social-media source"
    return 0, None


def score_sources(sources: list[dict]) -> list[dict]:
    """Score every source; returns copies sorted by score (desc).

    Input items are dicts with at least ``url`` and ``title``. Output items
    add ``credibility_score`` (int 0-100) and ``credibility_reasons``
    (list of human-readable signal descriptions). Ties break by URL so the
    ordering is fully deterministic.
    """
    prepared = []
    for src in sources:
        url = str(src.get("url", ""))
        host = _host(url)
        prepared.append(
            {
                "src": src,
                "url": url,
                "host": host,
                "tokens": _title_tokens(str(src.get("title", ""))),
            }
        )

    results: list[dict] = []
    for item in prepared:
        score = BASE_SCORE
        reasons: list[str] = []

        points, reason = _type_signal(item["host"])
        if points:
            score += points
        if reason:
            reasons.append(f"{reason} ({points:+d})")

        if item["url"].lower().startswith("https://"):
            score += 5
            reasons.append("served over HTTPS (+5)")
        elif item["url"].lower().startswith("http://"):
            score -= 5
            reasons.append("plain HTTP, not HTTPS (-5)")

        corroborators = 0
        for other in prepared:
            if other is item or other["host"] == item["host"]:
                continue
            if len(item["tokens"] & other["tokens"]) >= 2:
                corroborators += 1
        if corroborators:
            bonus = min(15, 5 * corroborators)
            score += bonus
            reasons.append(
                f"corroborated by {corroborators} independent domain(s) "
                f"with similar coverage (+{bonus})"
            )

        scored = dict(item["src"])
        scored["credibility_score"] = max(0, min(100, score))
        scored["credibility_reasons"] = reasons
        results.append(scored)

    results.sort(key=lambda s: (-s["credibility_score"], s.get("url", "")))
    return results
