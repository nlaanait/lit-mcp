from __future__ import annotations

from pathlib import Path

import pytest

from my_lit_mcp.config import init_workspace
from my_lit_mcp.db import Database
from my_lit_mcp import seeds as seed_svc
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


def test_seed_crud_local(workspace):
    cfg, db = workspace
    with db.session() as conn:
        seed = db.add_seed(
            conn,
            s2_id="seedpaper111",
            doi="10.1000/seed.1",
            title="Canonical Seed Paper",
            year=2020,
            notes="core",
        )
        assert seed["id"] >= 1
        listed = db.list_seeds(conn)
        assert len(listed) == 1
        assert db.enabled_seed_ids(conn) == ["seedpaper111"]

        db.set_seed_enabled(conn, seed["id"], False)
        assert db.enabled_seed_ids(conn) == []

        db.set_seed_enabled(conn, seed["id"], True)
        assert db.remove_seed(conn, seed_id=seed["id"]) is True
        assert db.list_seeds(conn) == []


def test_add_seed_service_without_network(workspace, monkeypatch):
    cfg, db = workspace

    class FakeRec:
        s2_id = "abcseed"
        doi = "10.1000/abc"
        title = "Fake Seed"
        year = 2021
        url = "https://example.com/p"

    monkeypatch.setattr(seed_svc.s2_src, "get_paper", lambda *a, **k: FakeRec())
    result = seed_svc.add_seed(cfg, doi="10.1000/abc", notes="via doi", db=db)
    assert result["ok"] is True
    assert result["seed"]["s2_id"] == "abcseed"
    listed = seed_svc.list_seeds(cfg, db=db)
    assert len(listed) == 1


def test_active_seed_ids_from_db(workspace):
    cfg, db = workspace
    with db.session() as conn:
        db.add_seed(conn, s2_id="dbseed1", title="One")
        db.add_seed(conn, s2_id="dbseed2", title="Two")
        db.set_seed_enabled(conn, db.get_seed_by_s2_id(conn, "dbseed2")["id"], False)
    ids = seed_svc.active_seed_ids(cfg, db=db)
    assert ids == ["dbseed1"]


@pytest.mark.asyncio
async def test_mcp_seed_tools_registered():
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert {
        "list_seeds",
        "resolve_seed",
        "add_seed",
        "remove_seed",
        "set_seed_enabled",
    } <= names
