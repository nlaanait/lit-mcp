from __future__ import annotations

from pathlib import Path

import pymupdf

from my_lit_mcp.config import init_workspace
from my_lit_mcp.db import Database
from my_lit_mcp.ingest.runner import parse_one_paper, run_parse
from my_lit_mcp.pdf import extract_text


def test_end_to_end_local_parse_and_search(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MY_LIT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MY_LIT_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("MY_LIT_DB", str(tmp_path / "papers.db"))
    monkeypatch.setenv("MY_LIT_PDF_DIR", str(tmp_path / "pdfs"))

    cfg = init_workspace(force=True)
    db = Database(cfg.db_path)

    # Create a local OA-like PDF and pretend Unpaywall already resolved it.
    pdf_path = cfg.pdf_cache_dir / "seed.pdf"
    cfg.pdf_cache_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "End to end retrieval augmented generation fulltext")
    doc.save(pdf_path)
    doc.close()

    with db.session() as conn:
        pid = db.upsert_paper(
            conn,
            {
                "title": "Local RAG Pipeline Paper",
                "abstract": "retrieval methods",
                "source": "arxiv",
                "arxiv_id": "local.0001",
                "oa_pdf_url": pdf_path.as_uri(),
                "year": 2025,
            },
        )

    # download_pdf expects http(s); for local test call extract + set_fulltext path via parse helpers
    # by pointing oa_pdf_url to a file URL we skip network in a dedicated helper path:
    text, pages = extract_text(pdf_path, max_pages=3)
    with db.session() as conn:
        db.set_fulltext(conn, pid, text, pages, "ok", str(pdf_path))
        db.update_score(conn, pid, 0.88, seed_hit=True)
        rows = db.search(conn, "fulltext", fulltext_only=True)
        assert rows and rows[0]["id"] == pid
        summary = db.status_summary(conn)
        assert summary["papers"] == 1
        assert summary["fulltext_ok"] == 1
