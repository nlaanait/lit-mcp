from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT,
    title TEXT NOT NULL,
    abstract TEXT,
    authors TEXT,
    year INTEGER,
    published_at TEXT,
    venue TEXT,
    url TEXT,
    source TEXT,
    s2_id TEXT,
    pmid TEXT,
    arxiv_id TEXT,
    openalex_id TEXT,
    oa_pdf_url TEXT,
    pdf_path TEXT,
    parse_status TEXT,
    score REAL DEFAULT 0,
    seed_hit INTEGER DEFAULT 0,
    ingested_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_papers_doi ON papers(doi) WHERE doi IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_papers_s2 ON papers(s2_id) WHERE s2_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_papers_pmid ON papers(pmid) WHERE pmid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_papers_arxiv ON papers(arxiv_id) WHERE arxiv_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_papers_openalex ON papers(openalex_id) WHERE openalex_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_papers_ingested ON papers(ingested_at);
CREATE INDEX IF NOT EXISTS idx_papers_score ON papers(score DESC);
CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);

CREATE TABLE IF NOT EXISTS paper_fulltext (
    paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    page_count INTEGER,
    parsed_at TEXT NOT NULL,
    parse_status TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    title,
    abstract,
    fulltext,
    tokenize='porter'
);

CREATE TABLE IF NOT EXISTS feedback (
    paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    notes TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    papers_seen INTEGER DEFAULT 0,
    papers_upserted INTEGER DEFAULT 0,
    pdfs_parsed INTEGER DEFAULT 0,
    openalex_calls INTEGER DEFAULT 0,
    detail_json TEXT
);

CREATE TABLE IF NOT EXISTS api_usage (
    day TEXT NOT NULL,
    provider TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, provider)
);

CREATE TABLE IF NOT EXISTS seeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    s2_id TEXT NOT NULL UNIQUE,
    doi TEXT,
    title TEXT,
    year INTEGER,
    url TEXT,
    notes TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_seeds_enabled ON seeds(enabled);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.session() as conn:
            conn.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _find_existing(self, conn: sqlite3.Connection, paper: dict[str, Any]) -> sqlite3.Row | None:
        for key in ("doi", "s2_id", "pmid", "arxiv_id", "openalex_id"):
            value = paper.get(key)
            if value:
                row = conn.execute(f"SELECT * FROM papers WHERE {key} = ?", (value,)).fetchone()
                if row:
                    return row
        return None

    def _refresh_fts(self, conn: sqlite3.Connection, paper_id: int) -> None:
        row = conn.execute("SELECT title, abstract FROM papers WHERE id = ?", (paper_id,)).fetchone()
        ft = conn.execute(
            "SELECT text FROM paper_fulltext WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        conn.execute("DELETE FROM papers_fts WHERE rowid = ?", (paper_id,))
        conn.execute(
            "INSERT INTO papers_fts(rowid, title, abstract, fulltext) VALUES (?, ?, ?, ?)",
            (
                paper_id,
                (row["title"] if row else "") or "",
                (row["abstract"] if row else "") or "",
                (ft["text"] if ft else "") or "",
            ),
        )

    def upsert_paper(self, conn: sqlite3.Connection, paper: dict[str, Any]) -> int:
        now = utc_now()
        existing = self._find_existing(conn, paper)
        fields = {
            "doi": paper.get("doi"),
            "title": paper.get("title") or "Untitled",
            "abstract": paper.get("abstract"),
            "authors": paper.get("authors"),
            "year": paper.get("year"),
            "published_at": paper.get("published_at"),
            "venue": paper.get("venue"),
            "url": paper.get("url"),
            "source": paper.get("source"),
            "s2_id": paper.get("s2_id"),
            "pmid": paper.get("pmid"),
            "arxiv_id": paper.get("arxiv_id"),
            "openalex_id": paper.get("openalex_id"),
            "oa_pdf_url": paper.get("oa_pdf_url"),
            "pdf_path": paper.get("pdf_path"),
            "parse_status": paper.get("parse_status"),
            "score": float(paper.get("score") or 0.0),
            "seed_hit": int(bool(paper.get("seed_hit"))),
            "updated_at": now,
        }
        if existing:
            paper_id = int(existing["id"])
            sets: list[str] = []
            values: list[Any] = []
            for key, value in fields.items():
                if value is None and key not in {"score", "seed_hit", "updated_at", "title"}:
                    continue
                if existing[key] and value in (None, ""):
                    continue
                sets.append(f"{key} = ?")
                values.append(value)
            if sets:
                values.append(paper_id)
                conn.execute(f"UPDATE papers SET {', '.join(sets)} WHERE id = ?", values)
            self._refresh_fts(conn, paper_id)
            return paper_id

        fields["ingested_at"] = now
        cols = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        cur = conn.execute(
            f"INSERT INTO papers ({cols}) VALUES ({placeholders})",
            list(fields.values()),
        )
        paper_id = int(cur.lastrowid)
        self._refresh_fts(conn, paper_id)
        return paper_id

    def set_fulltext(
        self,
        conn: sqlite3.Connection,
        paper_id: int,
        text: str,
        page_count: int | None,
        parse_status: str,
        pdf_path: str | None = None,
    ) -> None:
        now = utc_now()
        conn.execute(
            """
            INSERT INTO paper_fulltext(paper_id, text, page_count, parsed_at, parse_status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
              text=excluded.text,
              page_count=excluded.page_count,
              parsed_at=excluded.parsed_at,
              parse_status=excluded.parse_status
            """,
            (paper_id, text, page_count, now, parse_status),
        )
        conn.execute(
            "UPDATE papers SET parse_status=?, pdf_path=COALESCE(?, pdf_path), updated_at=? WHERE id=?",
            (parse_status, pdf_path, now, paper_id),
        )
        self._refresh_fts(conn, paper_id)

    def update_score(
        self, conn: sqlite3.Connection, paper_id: int, score: float, seed_hit: bool = False
    ) -> None:
        conn.execute(
            "UPDATE papers SET score=?, seed_hit=?, updated_at=? WHERE id=?",
            (score, int(seed_hit), utc_now(), paper_id),
        )

    def set_feedback(
        self, conn: sqlite3.Connection, paper_id: int, label: str, notes: str | None = None
    ) -> None:
        conn.execute(
            """
            INSERT INTO feedback(paper_id, label, notes, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
              label=excluded.label, notes=excluded.notes, updated_at=excluded.updated_at
            """,
            (paper_id, label, notes, utc_now()),
        )

    def get_paper(self, conn: sqlite3.Connection, paper_id: int) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        fb = conn.execute(
            "SELECT label, notes FROM feedback WHERE paper_id=?", (paper_id,)
        ).fetchone()
        data["feedback"] = dict(fb) if fb else None
        return data

    def get_fulltext(self, conn: sqlite3.Connection, paper_id: int) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM paper_fulltext WHERE paper_id=?", (paper_id,)
        ).fetchone()
        return dict(row) if row else None

    def search(
        self,
        conn: sqlite3.Connection,
        query: str,
        *,
        fulltext_only: bool = False,
        source: str | None = None,
        label: str | None = None,
        since: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        like = f"%{query}%"
        if fulltext_only:
            sql = """
                SELECT p.*, substr(ft.text, 1, 200) AS snippet
                FROM papers p
                JOIN paper_fulltext ft ON ft.paper_id = p.id
                LEFT JOIN feedback f ON f.paper_id = p.id
                WHERE ft.text LIKE ?
            """
            params: list[Any] = [like]
        else:
            sql = """
                SELECT p.*, substr(COALESCE(ft.text, p.abstract, ''), 1, 200) AS snippet
                FROM papers p
                LEFT JOIN paper_fulltext ft ON ft.paper_id = p.id
                LEFT JOIN feedback f ON f.paper_id = p.id
                WHERE (p.title LIKE ? OR IFNULL(p.abstract,'') LIKE ? OR IFNULL(ft.text,'') LIKE ?)
            """
            params = [like, like, like]
        if source:
            sql += " AND p.source = ?"
            params.append(source)
        if label:
            sql += " AND f.label = ?"
            params.append(label)
        if since:
            sql += " AND p.ingested_at >= ?"
            params.append(since)
        sql += " ORDER BY p.score DESC, p.ingested_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def papers_since(self, conn: sqlite3.Connection, since: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM papers WHERE ingested_at >= ? ORDER BY ingested_at DESC LIMIT ?",
            (since, max(1, min(limit, 200))),
        ).fetchall()
        return [dict(r) for r in rows]

    def must_read(self, conn: sqlite3.Connection, threshold: float, limit: int = 50) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT p.* FROM papers p
            LEFT JOIN feedback f ON f.paper_id = p.id
            WHERE p.score >= ? OR f.label = 'must_read'
            ORDER BY p.score DESC LIMIT ?
            """,
            (threshold, max(1, min(limit, 200))),
        ).fetchall()
        return [dict(r) for r in rows]

    def similar_to(self, conn: sqlite3.Connection, paper_id: int, limit: int = 10) -> list[dict[str, Any]]:
        paper = self.get_paper(conn, paper_id)
        if not paper:
            return []
        tokens = [t.lower() for t in (paper.get("title") or "").split() if len(t) > 3][:8]
        if not tokens:
            return []
        clauses = " OR ".join("lower(title) LIKE ?" for _ in tokens)
        params: list[Any] = [paper_id, *[f"%{t}%" for t in tokens], max(1, min(limit, 50))]
        rows = conn.execute(
            f"SELECT * FROM papers WHERE id != ? AND ({clauses}) ORDER BY score DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def list_papers_needing_pdf(self, conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT * FROM papers
            WHERE (parse_status IS NULL OR parse_status IN ('', 'no_pdf', 'error'))
              AND oa_pdf_url IS NOT NULL AND oa_pdf_url != ''
            ORDER BY score DESC, ingested_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def increment_api_usage(self, conn: sqlite3.Connection, provider: str, n: int = 1) -> int:
        day = date.today().isoformat()
        conn.execute(
            """
            INSERT INTO api_usage(day, provider, calls) VALUES (?, ?, ?)
            ON CONFLICT(day, provider) DO UPDATE SET calls = calls + excluded.calls
            """,
            (day, provider, n),
        )
        row = conn.execute(
            "SELECT calls FROM api_usage WHERE day=? AND provider=?", (day, provider)
        ).fetchone()
        return int(row["calls"]) if row else n

    def get_api_usage(self, conn: sqlite3.Connection, provider: str, day: str | None = None) -> int:
        day = day or date.today().isoformat()
        row = conn.execute(
            "SELECT calls FROM api_usage WHERE day=? AND provider=?", (day, provider)
        ).fetchone()
        return int(row["calls"]) if row else 0

    def start_run(self, conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            "INSERT INTO runs(started_at, status) VALUES (?, ?)",
            (utc_now(), "running"),
        )
        return int(cur.lastrowid)

    def finish_run(self, conn: sqlite3.Connection, run_id: int, **kwargs: Any) -> None:
        detail = kwargs.get("detail")
        conn.execute(
            """
            UPDATE runs SET finished_at=?, status=?, papers_seen=?, papers_upserted=?,
              pdfs_parsed=?, openalex_calls=?, detail_json=?
            WHERE id=?
            """,
            (
                utc_now(),
                kwargs.get("status", "ok"),
                kwargs.get("papers_seen", 0),
                kwargs.get("papers_upserted", 0),
                kwargs.get("pdfs_parsed", 0),
                kwargs.get("openalex_calls", 0),
                json.dumps(detail) if detail is not None else None,
                run_id,
            ),
        )

    def status_summary(self, conn: sqlite3.Connection) -> dict[str, Any]:
        papers = conn.execute("SELECT COUNT(*) AS c FROM papers").fetchone()["c"]
        parsed = conn.execute(
            "SELECT COUNT(*) AS c FROM paper_fulltext WHERE parse_status='ok'"
        ).fetchone()["c"]
        last = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "papers": papers,
            "fulltext_ok": parsed,
            "openalex_calls_today": self.get_api_usage(conn, "openalex"),
            "last_run": dict(last) if last else None,
        }

    def enabled_sources(self, conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT DISTINCT source FROM papers WHERE source IS NOT NULL ORDER BY source"
        ).fetchall()
        return [r["source"] for r in rows]

    def list_seeds(
        self, conn: sqlite3.Connection, *, enabled_only: bool = False
    ) -> list[dict[str, Any]]:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM seeds WHERE enabled = 1 ORDER BY id ASC"
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM seeds ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]

    def get_seed(self, conn: sqlite3.Connection, seed_id: int) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM seeds WHERE id = ?", (seed_id,)).fetchone()
        return dict(row) if row else None

    def get_seed_by_s2_id(self, conn: sqlite3.Connection, s2_id: str) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM seeds WHERE s2_id = ?", (s2_id,)).fetchone()
        return dict(row) if row else None

    def add_seed(
        self,
        conn: sqlite3.Connection,
        *,
        s2_id: str,
        doi: str | None = None,
        title: str | None = None,
        year: int | None = None,
        url: str | None = None,
        notes: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        now = utc_now()
        existing = self.get_seed_by_s2_id(conn, s2_id)
        if existing:
            conn.execute(
                """
                UPDATE seeds SET
                  doi = COALESCE(?, doi),
                  title = COALESCE(?, title),
                  year = COALESCE(?, year),
                  url = COALESCE(?, url),
                  notes = COALESCE(?, notes),
                  enabled = ?,
                  updated_at = ?
                WHERE s2_id = ?
                """,
                (doi, title, year, url, notes, int(enabled), now, s2_id),
            )
            return self.get_seed_by_s2_id(conn, s2_id) or existing
        cur = conn.execute(
            """
            INSERT INTO seeds(s2_id, doi, title, year, url, notes, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (s2_id, doi, title, year, url, notes, int(enabled), now, now),
        )
        return self.get_seed(conn, int(cur.lastrowid)) or {
            "id": int(cur.lastrowid),
            "s2_id": s2_id,
        }

    def remove_seed(
        self,
        conn: sqlite3.Connection,
        *,
        seed_id: int | None = None,
        s2_id: str | None = None,
    ) -> bool:
        if seed_id is not None:
            cur = conn.execute("DELETE FROM seeds WHERE id = ?", (seed_id,))
            return cur.rowcount > 0
        if s2_id:
            cur = conn.execute("DELETE FROM seeds WHERE s2_id = ?", (s2_id,))
            return cur.rowcount > 0
        raise ValueError("Provide seed_id or s2_id")

    def set_seed_enabled(
        self, conn: sqlite3.Connection, seed_id: int, enabled: bool
    ) -> dict[str, Any] | None:
        conn.execute(
            "UPDATE seeds SET enabled = ?, updated_at = ? WHERE id = ?",
            (int(enabled), utc_now(), seed_id),
        )
        return self.get_seed(conn, seed_id)

    def enabled_seed_ids(self, conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT s2_id FROM seeds WHERE enabled = 1 ORDER BY id ASC"
        ).fetchall()
        return [r["s2_id"] for r in rows]
