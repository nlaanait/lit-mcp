from __future__ import annotations

import time
from typing import Any

import httpx

from my_lit_mcp.ingest import PaperRecord, normalize_doi

S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_PAPER = "https://api.semanticscholar.org/graph/v1/paper/{paper_id}"
S2_RECS = "https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{paper_id}"
S2_FIELDS = "title,abstract,authors,year,venue,url,externalIds,openAccessPdf"


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _from_s2(item: dict[str, Any], *, seed_hit: bool = False) -> PaperRecord:
    authors = ", ".join(
        a.get("name", "") for a in (item.get("authors") or []) if a.get("name")
    ) or None
    external = item.get("externalIds") or {}
    year = item.get("year")
    return PaperRecord(
        title=(item.get("title") or "Untitled").strip(),
        abstract=item.get("abstract"),
        authors=authors,
        year=year,
        published_at=str(year) if year else None,
        venue=item.get("venue") or None,
        url=item.get("url"),
        source="s2",
        doi=normalize_doi(external.get("DOI")),
        s2_id=item.get("paperId"),
        pmid=str(external["PubMed"]) if external.get("PubMed") else None,
        arxiv_id=external.get("ArXiv"),
        oa_pdf_url=(item.get("openAccessPdf") or {}).get("url"),
        seed_hit=seed_hit,
    )


def search_s2(
    query: str,
    *,
    api_key: str = "",
    max_results: int = 25,
    sleep_seconds: float = 1.1,
) -> list[PaperRecord]:
    params = {
        "query": query,
        "limit": max_results,
        "fields": S2_FIELDS,
    }
    with httpx.Client(timeout=60.0, headers=_headers(api_key)) as client:
        resp = client.get(S2_SEARCH, params=params)
        resp.raise_for_status()
        time.sleep(sleep_seconds)
        return [_from_s2(item) for item in (resp.json().get("data") or [])]


def get_paper(
    paper_id: str,
    *,
    api_key: str = "",
    sleep_seconds: float = 1.1,
) -> PaperRecord | None:
    """Fetch one paper by S2 paperId, DOI (DOI:...), ArXiv (ARXIV:...), or CorpusId."""
    params = {"fields": S2_FIELDS}
    with httpx.Client(timeout=60.0, headers=_headers(api_key)) as client:
        resp = client.get(S2_PAPER.format(paper_id=paper_id), params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        time.sleep(sleep_seconds)
        return _from_s2(resp.json())


def recommendations_for_seed(
    paper_id: str,
    *,
    api_key: str = "",
    limit: int = 20,
    sleep_seconds: float = 1.1,
) -> list[PaperRecord]:
    params = {
        "limit": limit,
        "fields": S2_FIELDS,
    }
    with httpx.Client(timeout=60.0, headers=_headers(api_key)) as client:
        resp = client.get(S2_RECS.format(paper_id=paper_id), params=params)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        time.sleep(sleep_seconds)
        return [
            _from_s2(item, seed_hit=True)
            for item in (resp.json().get("recommendedPapers") or [])
        ]
