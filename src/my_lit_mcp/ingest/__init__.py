from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class PaperRecord:
    title: str
    abstract: str | None = None
    authors: str | None = None
    year: int | None = None
    published_at: str | None = None
    venue: str | None = None
    url: str | None = None
    source: str | None = None
    doi: str | None = None
    s2_id: str | None = None
    pmid: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = None
    oa_pdf_url: str | None = None
    seed_hit: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    value = str(doi).strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.lower().startswith(prefix):
            value = value[len(prefix) :]
            break
    return value.strip() or None
