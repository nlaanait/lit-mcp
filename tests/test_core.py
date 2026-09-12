from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from my_lit_mcp.config import RankingConfig, init_workspace, load_config
from my_lit_mcp.db import Database
from my_lit_mcp.ingest.sources.openalex import OpenAlexBudgetExceeded, search_openalex
from my_lit_mcp.pdf import extract_text
from my_lit_mcp.rank import score_paper
from my_lit_mcp.server import server


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MY_LIT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MY_LIT_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("MY_LIT_DB", str(tmp_path / "papers.db"))
    monkeypatch.setenv("MY_LIT_PDF_DIR", str(tmp_path / "pdfs"))
    cfg = init_workspace(force=True)
    db = Database(cfg.db_path)
    return cfg, db


def test_upsert_idempotent(workspace):
    cfg, db = workspace
    payload = {
        "title": "A Paper About Embeddings",
        "abstract": "retrieval and embeddings",
        "doi": "10.1000/test.doi",
        "source": "arxiv",
        "year": 2023,
    }
    with db.session() as conn:
        a = db.upsert_paper(conn, payload)
        b = db.upsert_paper(conn, {**payload, "abstract": "updated abstract"})
        assert a == b
        paper = db.get_paper(conn, a)
        assert paper["abstract"] == "updated abstract"
        assert db.status_summary(conn)["papers"] == 1


def test_ranking_include_exclude_and_seed():
    ranking = RankingConfig(
        include_terms=["retrieval", "embedding"],
        exclude_terms=["survey only"],
        weight_seed=0.6,
        weight_keyword=0.3,
        weight_recency=0.1,
    )
    paper = {
        "title": "Retrieval with embeddings",
        "abstract": "dense retrieval",
        "year": 2024,
        "published_at": "2024-06-01",
    }
    high = score_paper(paper, ranking, seed_hit=True)
    low = score_paper(
        {"title": "survey only overview", "abstract": "survey only", "year": 2010},
        ranking,
        seed_hit=False,
    )
    assert high > 0.7
    assert low < 0.2


def test_openalex_daily_cap(monkeypatch):
    with pytest.raises(OpenAlexBudgetExceeded):
        search_openalex(
            "anything",
            api_key="free-key",
            calls_used_today=800,
            max_calls_per_day=800,
        )


def test_pdf_extract(tmp_path: Path):
    pdf_path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello open access full text parsing")
    doc.save(pdf_path)
    doc.close()
    text, pages = extract_text(pdf_path, max_pages=2)
    assert "full text parsing" in text
    assert pages == 1


def test_search_and_feedback_tools(workspace):
    cfg, db = workspace
    with db.session() as conn:
        pid = db.upsert_paper(
            conn,
            {
                "title": "Local search for retrieval papers",
                "abstract": "about retrieval systems",
                "source": "s2",
                "s2_id": "abc123",
                "year": 2022,
            },
        )
        db.update_score(conn, pid, 0.9, seed_hit=True)
        db.set_fulltext(conn, pid, "body mentions retrieval pipeline", 1, "ok")
        db.set_feedback(conn, pid, "must_read", "great")
        rows = db.search(conn, "retrieval")
        assert rows and rows[0]["id"] == pid
        must = db.must_read(conn, 0.55)
        assert must and must[0]["id"] == pid


@pytest.mark.asyncio
async def test_mcp_tools_registered():
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert {
        "list_queries",
        "search_local",
        "search_fulltext",
        "get_paper",
        "get_fulltext",
        "new_since",
        "must_read",
        "similar_to",
        "mark_feedback",
        "pipeline_status",
    } <= names


def test_load_config_queries(workspace):
    cfg, _ = workspace
    loaded = load_config(cfg.config_path)
    assert any(q.source == "arxiv" for q in loaded.queries)
