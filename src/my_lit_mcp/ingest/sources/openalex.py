from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from my_lit_mcp.ingest import PaperRecord, normalize_doi

OPENALEX_BASE = "https://api.openalex.org"


class OpenAlexBudgetExceeded(RuntimeError):
    pass


def search_openalex(
    query: str,
    *,
    api_key: str,
    max_results: int = 25,
    sleep_seconds: float = 0.2,
    calls_used_today: int = 0,
    max_calls_per_day: int = 800,
    record_call: Callable[[], None] | None = None,
) -> list[PaperRecord]:
    if not api_key:
        raise ValueError("OPENALEX_API_KEY is required for OpenAlex search (free key, no payment).")
    if calls_used_today >= max_calls_per_day:
        raise OpenAlexBudgetExceeded(
            f"OpenAlex daily free-search cap reached ({max_calls_per_day}). Skipping until tomorrow."
        )
    params = {
        "search": query,
        "per_page": min(max_results, 50),
        "api_key": api_key,
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(f"{OPENALEX_BASE}/works", params=params)
        if resp.status_code == 429:
            raise OpenAlexBudgetExceeded("OpenAlex returned HTTP 429; stopping OpenAlex for today.")
        resp.raise_for_status()
        if record_call:
            record_call()
        time.sleep(sleep_seconds)
        return [_from_openalex(item) for item in (resp.json().get("results") or [])]


def _from_openalex(item: dict[str, Any]) -> PaperRecord:
    ids = item.get("ids") or {}
    authorships = item.get("authorships") or []
    authors = ", ".join(
        (a.get("author") or {}).get("display_name", "")
        for a in authorships
        if (a.get("author") or {}).get("display_name")
    ) or None
    primary = item.get("primary_location") or {}
    venue = (primary.get("source") or {}).get("display_name")
    oa = item.get("open_access") or {}
    pdf = oa.get("oa_url") or primary.get("pdf_url")
    year = item.get("publication_year")
    openalex_id = item.get("id") or ids.get("openalex")
    if isinstance(openalex_id, str) and openalex_id.startswith("https://openalex.org/"):
        openalex_id = openalex_id.rsplit("/", 1)[-1]
    pmid = None
    pmid_url = ids.get("pmid")
    if pmid_url and "/" in str(pmid_url):
        pmid = str(pmid_url).rstrip("/").rsplit("/", 1)[-1]
    return PaperRecord(
        title=(item.get("title") or item.get("display_name") or "Untitled").strip(),
        abstract=_invert_abstract(item.get("abstract_inverted_index")),
        authors=authors,
        year=year,
        published_at=item.get("publication_date") or (str(year) if year else None),
        venue=venue,
        url=ids.get("openalex") or item.get("id"),
        source="openalex",
        doi=normalize_doi(ids.get("doi") or item.get("doi")),
        openalex_id=openalex_id,
        pmid=pmid,
        oa_pdf_url=pdf,
    )


def _invert_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    if not inverted:
        return None
    max_pos = max((pos for positions in inverted.values() for pos in positions), default=-1)
    if max_pos < 0:
        return None
    words = [""] * (max_pos + 1)
    for word, positions in inverted.items():
        for pos in positions:
            if 0 <= pos < len(words):
                words[pos] = word
    text = " ".join(w for w in words if w)
    return text or None
