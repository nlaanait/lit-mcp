from __future__ import annotations

from pathlib import Path

import httpx
import pymupdf


def download_pdf(url: str, dest: Path, *, timeout: float = 120.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.content
        if not data.startswith(b"%PDF"):
            raise ValueError(f"URL did not return a PDF: {url}")
        dest.write_bytes(data)
    return dest


def extract_text(pdf_path: Path, *, max_pages: int = 40) -> tuple[str, int]:
    doc = pymupdf.open(pdf_path)
    try:
        page_count = doc.page_count
        limit = min(page_count, max_pages)
        chunks = [doc.load_page(i).get_text("text") for i in range(limit)]
        return "\n".join(chunks).strip(), page_count
    finally:
        doc.close()
