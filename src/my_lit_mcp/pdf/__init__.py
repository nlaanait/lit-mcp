from __future__ import annotations

from pathlib import Path

import httpx
import pymupdf

from my_lit_mcp.pdf.urls import iter_pdf_urls, normalize_pdf_url

__all__ = ["download_pdf", "extract_text", "iter_pdf_urls", "normalize_pdf_url"]


def download_pdf(
    url: str,
    dest: Path,
    *,
    timeout: float = 120.0,
    doi: str | None = None,
    arxiv_id: str | None = None,
    venue: str | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    last_error: Exception | None = None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; my-lit-mcp/1.0; +https://github.com/cursor/my-lit-mcp)"
        ),
        "Accept": "application/pdf,*/*",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for candidate in iter_pdf_urls(
            url, doi=doi, arxiv_id=arxiv_id, venue=venue
        ):
            try:
                resp = client.get(candidate)
                resp.raise_for_status()
                data = resp.content
                if not data.startswith(b"%PDF"):
                    raise ValueError(f"URL did not return a PDF: {candidate}")
                dest.write_bytes(data)
                return dest
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

    if last_error:
        raise last_error
    raise ValueError(f"No PDF URL candidates for: {url}")


def extract_text(pdf_path: Path, *, max_pages: int = 40) -> tuple[str, int]:
    doc = pymupdf.open(pdf_path)
    try:
        page_count = doc.page_count
        limit = min(page_count, max_pages)
        chunks = [doc.load_page(i).get_text("text") for i in range(limit)]
        return "\n".join(chunks).strip(), page_count
    finally:
        doc.close()
