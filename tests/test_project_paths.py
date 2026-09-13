from __future__ import annotations

from pathlib import Path

import pytest

from my_lit_mcp.config import (
    MARKER_NAME,
    default_data_dir,
    ensure_workspace,
    init_workspace,
    load_config,
)


def test_init_requires_data_dir_without_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MY_LIT_DATA_DIR", raising=False)
    monkeypatch.delenv("MY_LIT_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="data directory"):
        init_workspace(project_root=tmp_path)


def test_init_writes_project_marker_and_scoped_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("MY_LIT_DATA_DIR", raising=False)
    monkeypatch.delenv("MY_LIT_CONFIG", raising=False)
    monkeypatch.delenv("MY_LIT_DB", raising=False)
    monkeypatch.delenv("MY_LIT_PDF_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    data_dir = tmp_path / "lit-data"
    cfg = init_workspace(data_dir=data_dir, project_root=tmp_path, force=True)

    marker = tmp_path / MARKER_NAME
    assert marker.is_file()
    assert data_dir.resolve().as_posix() in marker.read_text(encoding="utf-8")
    assert cfg.config_path == data_dir / "config.yaml"
    assert cfg.db_path == data_dir / "papers.db"
    assert cfg.pdf_cache_dir == data_dir / "pdfs"
    assert cfg.config_path.is_file()
    assert cfg.pdf_cache_dir.is_dir()

    monkeypatch.delenv("MY_LIT_DATA_DIR", raising=False)
    assert default_data_dir() == data_dir.resolve()
    loaded = load_config()
    assert loaded.db_path == data_dir / "papers.db"


def test_ensure_workspace_creates_dot_my_lit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("MY_LIT_DATA_DIR", raising=False)
    monkeypatch.delenv("MY_LIT_CONFIG", raising=False)
    monkeypatch.delenv("MY_LIT_DB", raising=False)
    monkeypatch.delenv("MY_LIT_PDF_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    cfg, created = ensure_workspace(project_root=tmp_path)
    assert created is True
    assert (tmp_path / ".my-lit" / "config.yaml").is_file()
    assert cfg.db_path == tmp_path / ".my-lit" / "papers.db"

    cfg2, created2 = ensure_workspace(project_root=tmp_path)
    assert created2 is False
    assert cfg2.config_path == cfg.config_path
