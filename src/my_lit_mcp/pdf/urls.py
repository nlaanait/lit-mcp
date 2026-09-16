from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import unquote, urlparse

from my_lit_mcp.ingest import normalize_doi

_DOI_IN_URL = re.compile(r"doi\.org/(.+)$", re.I)
_VERSIONED_PREPRINT = re.compile(
    r"(https?://(?:www\.)?(?:bio|med)rxiv\.org/content/)(.+?)(?:\.full)?\.pdf?$",
    re.I,
)
_CONTENT_PREPRINT = re.compile(
    r"(https?://(?:www\.)?(?:bio|med)rxiv\.org/content/)(.+?)(?:/)?$",
    re.I,
)


def extract_doi_from_url(url: str) -> str | None:
    match = _DOI_IN_URL.search(url.strip())
    if not match:
        return None
    return normalize_doi(unquote(match.group(1)))


def _looks_like_direct_pdf(url: str) -> bool:
    lower = url.lower()
    if lower.endswith(".pdf"):
        return True
    if ".full.pdf" in lower:
        return True
    if "arxiv.org/pdf/" in lower:
        return True
    return False


def _preprint_hosts(
    doi: str, *, venue: str | None = None, url: str | None = None
) -> list[str]:
    v = (venue or "").lower()
    u = (url or "").lower()
    if "medrxiv" in v or "medrxiv.org" in u:
        return ["www.medrxiv.org"]
    if "biorxiv" in v or "biorxiv.org" in u:
        return ["www.biorxiv.org"]
    if doi.startswith("10.64898/"):
        # Shared prefix for bioRxiv and medRxiv; try both.
        return ["www.biorxiv.org", "www.medrxiv.org"]
    if doi.startswith("10.1101/"):
        if "medrxiv" in u:
            return ["www.medrxiv.org"]
        return ["www.biorxiv.org"]
    return []


def _preprint_pdf_candidates(doi: str, host: str) -> list[str]:
    doi = normalize_doi(doi)
    if not doi:
        return []
    base = f"https://{host}/content/{doi}"
    # Latest versions first; most preprints are v1–v2.
    return [f"{base}v{version}.full.pdf" for version in (2, 1, 3, 4, 5)]


def _arxiv_pdf_url(*, arxiv_id: str | None = None, doi: str | None = None) -> str | None:
    if arxiv_id:
        aid = arxiv_id.strip().removesuffix(".pdf")
        return f"https://arxiv.org/pdf/{aid}.pdf"
    doi = normalize_doi(doi)
    if doi and doi.lower().startswith("10.48550/arxiv."):
        aid = doi.split("arxiv.", 1)[1]
        return f"https://arxiv.org/pdf/{aid}.pdf"
    return None


def _fix_preprint_page_url(url: str) -> str | None:
    match = _VERSIONED_PREPRINT.match(url.strip())
    if match:
        prefix, path = match.groups()
        path = path.rstrip("/")
        if not path.endswith(".full.pdf"):
            return f"{prefix}{path}.full.pdf"
        return url
    match = _CONTENT_PREPRINT.match(url.strip())
    if match:
        prefix, path = match.groups()
        path = path.rstrip("/")
        if re.search(r"v\d+$", path):
            return f"{prefix}{path}.full.pdf"
    return None


def normalize_pdf_url(
    url: str | None,
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    venue: str | None = None,
) -> str | None:
    """Return the best-guess direct PDF URL for storage."""
    doi = normalize_doi(doi) or (extract_doi_from_url(url) if url else None)

    if url and _looks_like_direct_pdf(url):
        fixed = _fix_preprint_page_url(url)
        return fixed or url

    if url and not _looks_like_direct_pdf(url):
        fixed = _fix_preprint_page_url(url)
        if fixed:
            return fixed

    arxiv_url = _arxiv_pdf_url(arxiv_id=arxiv_id, doi=doi)
    if arxiv_url:
        return arxiv_url

    if doi:
        for host in _preprint_hosts(doi, venue=venue, url=url):
            candidates = _preprint_pdf_candidates(doi, host)
            if candidates:
                return candidates[0]

    if url and "doi.org/" in url.lower() and doi:
        # doi.org landing pages are HTML; fall back to preprint/arXiv patterns above.
        return None

    return url


def iter_pdf_urls(
    url: str | None,
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    venue: str | None = None,
) -> Iterator[str]:
    """Yield PDF URLs to try, best first, without duplicates."""
    seen: set[str] = set()

    def add(candidate: str | None) -> Iterator[str]:
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        yield candidate

    normalized = normalize_pdf_url(
        url, doi=doi, arxiv_id=arxiv_id, venue=venue
    )
    yield from add(normalized)
    yield from add(url)

    doi = normalize_doi(doi) or (extract_doi_from_url(url) if url else None)
    yield from add(_arxiv_pdf_url(arxiv_id=arxiv_id, doi=doi))

    if doi:
        for host in _preprint_hosts(doi, venue=venue, url=url):
            for candidate in _preprint_pdf_candidates(doi, host):
                yield from add(candidate)

    if url:
        fixed = _fix_preprint_page_url(url)
        yield from add(fixed)
