from __future__ import annotations

import time

import httpx

from my_lit_mcp.ingest import normalize_doi


def resolve_oa_pdf(doi: str | None, *, email: str, sleep_seconds: float = 0.2) -> str | None:
    doi_norm = normalize_doi(doi)
    if not doi_norm or not email:
        return None
    with httpx.Client(timeout=60.0) as client:
        resp = client.get(
            f"https://api.unpaywall.org/v2/{doi_norm}",
            params={"email": email},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        time.sleep(sleep_seconds)
        data = resp.json()
        best = data.get("best_oa_location") or {}
        return best.get("url_for_pdf") or best.get("url")
