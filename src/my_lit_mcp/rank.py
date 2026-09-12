from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from my_lit_mcp.config import RankingConfig


def keyword_hit(text: str, ranking: RankingConfig) -> float:
    blob = (text or "").lower()
    if not blob:
        return 0.0
    includes = [t.lower() for t in ranking.include_terms if t.strip()]
    excludes = [t.lower() for t in ranking.exclude_terms if t.strip()]
    if excludes and any(term in blob for term in excludes):
        return 0.0
    if not includes:
        return 0.5
    return sum(1 for term in includes if term in blob) / len(includes)


def recency_score(published_at: str | None, year: int | None) -> float:
    now = datetime.now(timezone.utc)
    year_val = year
    if published_at:
        match = re.match(r"(\d{4})", published_at)
        if match:
            year_val = int(match.group(1))
    if not year_val:
        return 0.4
    age = max(0, now.year - int(year_val))
    if age <= 1:
        return 1.0
    if age <= 3:
        return 0.7
    if age <= 7:
        return 0.4
    return 0.2


def feedback_adjust(label: str | None) -> float:
    return {
        "must_read": 0.25,
        "relevant": 0.1,
        "not_relevant": -0.35,
    }.get(label or "", 0.0)


def score_paper(
    paper: dict[str, Any],
    ranking: RankingConfig,
    *,
    fulltext: str | None = None,
    feedback_label: str | None = None,
    seed_hit: bool = False,
) -> float:
    parts = [paper.get("title") or "", paper.get("abstract") or ""]
    if ranking.match_fulltext and fulltext:
        parts.append(fulltext)
    text = "\n".join(parts)
    seed = 1.0 if seed_hit or paper.get("seed_hit") else 0.0
    raw = (
        ranking.weight_seed * seed
        + ranking.weight_keyword * keyword_hit(text, ranking)
        + ranking.weight_recency * recency_score(paper.get("published_at"), paper.get("year"))
        + feedback_adjust(feedback_label)
    )
    return max(0.0, min(1.0, raw))
