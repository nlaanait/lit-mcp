from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from my_lit_mcp.config import load_config
from my_lit_mcp.db import Database
from my_lit_mcp import seeds as seed_svc

server = MCPServer(
    name="my-lit-mcp",
    instructions=(
        "Local literature corpus tools. Manage seed papers and search/read papers "
        "already ingested into the SQLite pipeline. Prefer seed MCP tools over "
        "editing config files."
    ),
)


def _db():
    cfg = load_config()
    return cfg, Database(cfg.db_path)


@server.tool()
def list_queries() -> str:
    """List configured ingest queries."""
    cfg, _ = _db()
    return json.dumps(
        [
            {
                "name": q.name,
                "source": q.source,
                "query": q.query,
                "enabled": q.enabled,
            }
            for q in cfg.queries
        ],
        indent=2,
    )


@server.tool()
def list_seeds(enabled_only: bool = False) -> str:
    """List seed papers stored in the local DB (preferred over config.yaml)."""
    cfg, db = _db()
    rows = seed_svc.list_seeds(cfg, enabled_only=enabled_only, db=db)
    return json.dumps(rows, indent=2, default=str)


@server.tool()
def resolve_seed(
    s2_id: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    title_query: str | None = None,
    paper_id: int | None = None,
) -> str:
    """Look up seed candidate metadata without saving. Use before add_seed if unsure."""
    cfg, db = _db()
    result = seed_svc.resolve_seed_candidate(
        cfg,
        s2_id=s2_id,
        doi=doi,
        arxiv_id=arxiv_id,
        title_query=title_query,
        paper_id=paper_id,
        db=db,
    )
    return json.dumps(result, indent=2, default=str)


@server.tool()
def add_seed(
    s2_id: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    title_query: str | None = None,
    paper_id: int | None = None,
    notes: str | None = None,
    enabled: bool = True,
) -> str:
    """Add or update a seed paper in the DB. Prefer s2_id or doi; title_query returns candidates."""
    cfg, db = _db()
    result = seed_svc.add_seed(
        cfg,
        s2_id=s2_id,
        doi=doi,
        arxiv_id=arxiv_id,
        title_query=title_query,
        paper_id=paper_id,
        notes=notes,
        enabled=enabled,
        db=db,
    )
    return json.dumps(result, indent=2, default=str)


@server.tool()
def remove_seed(seed_id: int | None = None, s2_id: str | None = None) -> str:
    """Delete a seed by local seed_id or Semantic Scholar s2_id."""
    cfg, db = _db()
    if seed_id is None and not s2_id:
        return json.dumps({"error": "missing_input", "hint": "Provide seed_id or s2_id"})
    result = seed_svc.remove_seed(cfg, seed_id=seed_id, s2_id=s2_id, db=db)
    return json.dumps(result, indent=2, default=str)


@server.tool()
def set_seed_enabled(seed_id: int, enabled: bool = True) -> str:
    """Enable or disable a seed without deleting it."""
    cfg, db = _db()
    result = seed_svc.set_seed_enabled(cfg, seed_id, enabled, db=db)
    return json.dumps(result, indent=2, default=str)


@server.tool()
def search_local(
    query: str,
    source: str | None = None,
    label: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> str:
    """Search title/abstract/fulltext in the local corpus."""
    _, db = _db()
    with db.session() as conn:
        rows = db.search(
            conn,
            query,
            fulltext_only=False,
            source=source,
            label=label,
            since=since,
            limit=limit,
        )
    return json.dumps(rows, indent=2, default=str)


@server.tool()
def search_fulltext(query: str, source: str | None = None, limit: int = 20) -> str:
    """Search only parsed PDF body text."""
    _, db = _db()
    with db.session() as conn:
        rows = db.search(conn, query, fulltext_only=True, source=source, limit=limit)
    return json.dumps(rows, indent=2, default=str)


@server.tool()
def get_paper(paper_id: int) -> str:
    """Fetch one paper with feedback and parse status."""
    _, db = _db()
    with db.session() as conn:
        row = db.get_paper(conn, paper_id)
    if not row:
        return json.dumps({"error": "not_found", "paper_id": paper_id})
    return json.dumps(row, indent=2, default=str)


@server.tool()
def get_fulltext(paper_id: int, max_chars: int = 20000) -> str:
    """Return stored full text (truncated)."""
    _, db = _db()
    with db.session() as conn:
        row = db.get_fulltext(conn, paper_id)
    if not row:
        return json.dumps({"error": "no_fulltext", "paper_id": paper_id})
    text = row.get("text") or ""
    payload = dict(row)
    payload["text"] = text[: max(0, max_chars)]
    payload["truncated"] = len(text) > max_chars
    payload["total_chars"] = len(text)
    return json.dumps(payload, indent=2, default=str)


@server.tool()
def new_since(since: str, limit: int = 50) -> str:
    """Papers ingested after an ISO timestamp."""
    _, db = _db()
    with db.session() as conn:
        rows = db.papers_since(conn, since, limit=limit)
    return json.dumps(rows, indent=2, default=str)


@server.tool()
def must_read(limit: int = 50) -> str:
    """High-score or must_read-labeled papers."""
    cfg, db = _db()
    with db.session() as conn:
        rows = db.must_read(conn, cfg.ranking.must_read_threshold, limit=limit)
    return json.dumps(rows, indent=2, default=str)


@server.tool()
def similar_to(paper_id: int, limit: int = 10) -> str:
    """Local title-keyword similarity."""
    _, db = _db()
    with db.session() as conn:
        rows = db.similar_to(conn, paper_id, limit=limit)
    return json.dumps(rows, indent=2, default=str)


@server.tool()
def mark_feedback(paper_id: int, label: str, notes: str | None = None) -> str:
    """Upsert feedback: relevant | not_relevant | must_read."""
    allowed = {"relevant", "not_relevant", "must_read"}
    if label not in allowed:
        return json.dumps({"error": "invalid_label", "allowed": sorted(allowed)})
    _, db = _db()
    with db.session() as conn:
        if not db.get_paper(conn, paper_id):
            return json.dumps({"error": "not_found", "paper_id": paper_id})
        db.set_feedback(conn, paper_id, label, notes)
    return json.dumps({"ok": True, "paper_id": paper_id, "label": label})


@server.tool()
def pipeline_status() -> str:
    """Last run, OpenAlex daily calls, PDF parse counts, seed count."""
    cfg, db = _db()
    with db.session() as conn:
        summary = db.status_summary(conn)
        summary["seeds"] = len(db.list_seeds(conn))
        summary["seeds_enabled"] = len(db.enabled_seed_ids(conn))
    return json.dumps(summary, indent=2, default=str)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
