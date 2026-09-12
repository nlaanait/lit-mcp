from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from my_lit_mcp.config import load_config
from my_lit_mcp.db import Database

server = MCPServer(
    name="my-lit-mcp",
    instructions=(
        "Local literature corpus tools. Search and read papers already ingested "
        "into the SQLite pipeline; do not assume live web search."
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
    """Last run, OpenAlex daily calls, PDF parse counts."""
    _, db = _db()
    with db.session() as conn:
        return json.dumps(db.status_summary(conn), indent=2, default=str)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
