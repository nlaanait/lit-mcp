from __future__ import annotations

from typing import Any

from my_lit_mcp.config import AppConfig
from my_lit_mcp.db import Database
from my_lit_mcp.ingest import normalize_doi
from my_lit_mcp.ingest.sources import s2 as s2_src


def _lookup_id_from_inputs(
    *,
    s2_id: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
) -> str | None:
    if s2_id:
        return s2_id.strip()
    doi_norm = normalize_doi(doi)
    if doi_norm:
        return f"DOI:{doi_norm}"
    if arxiv_id:
        aid = arxiv_id.strip()
        if not aid.upper().startswith("ARXIV:"):
            aid = f"ARXIV:{aid}"
        return aid
    return None


def resolve_seed_candidate(
    cfg: AppConfig,
    *,
    s2_id: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    title_query: str | None = None,
    paper_id: int | None = None,
    db: Database | None = None,
) -> dict[str, Any]:
    """Resolve metadata for a seed without writing to the DB."""
    database = db or Database(cfg.db_path)

    if paper_id is not None:
        with database.session() as conn:
            paper = database.get_paper(conn, paper_id)
        if not paper:
            return {"error": "not_found", "paper_id": paper_id}
        if not paper.get("s2_id") and paper.get("doi"):
            rec = s2_src.get_paper(
                f"DOI:{normalize_doi(paper['doi'])}",
                api_key=cfg.semantic_scholar_api_key,
                sleep_seconds=cfg.rate_limits.s2_sleep_seconds,
            )
            if rec and rec.s2_id:
                return {
                    "s2_id": rec.s2_id,
                    "doi": rec.doi or paper.get("doi"),
                    "title": rec.title or paper.get("title"),
                    "year": rec.year or paper.get("year"),
                    "url": rec.url or paper.get("url"),
                    "source": "local_paper+s2",
                }
        if not paper.get("s2_id"):
            return {
                "error": "missing_s2_id",
                "hint": "Local paper has no Semantic Scholar id; pass doi/s2_id/title_query instead.",
                "paper": paper,
            }
        return {
            "s2_id": paper["s2_id"],
            "doi": paper.get("doi"),
            "title": paper.get("title"),
            "year": paper.get("year"),
            "url": paper.get("url"),
            "source": "local_paper",
        }

    lookup = _lookup_id_from_inputs(s2_id=s2_id, doi=doi, arxiv_id=arxiv_id)
    if lookup:
        rec = s2_src.get_paper(
            lookup,
            api_key=cfg.semantic_scholar_api_key,
            sleep_seconds=cfg.rate_limits.s2_sleep_seconds,
        )
        if not rec or not rec.s2_id:
            return {"error": "not_found", "lookup": lookup}
        return {
            "s2_id": rec.s2_id,
            "doi": rec.doi,
            "title": rec.title,
            "year": rec.year,
            "url": rec.url,
            "source": "s2_lookup",
        }

    if title_query:
        hits = s2_src.search_s2(
            title_query,
            api_key=cfg.semantic_scholar_api_key,
            max_results=5,
            sleep_seconds=cfg.rate_limits.s2_sleep_seconds,
        )
        return {
            "candidates": [
                {
                    "s2_id": h.s2_id,
                    "doi": h.doi,
                    "title": h.title,
                    "year": h.year,
                    "url": h.url,
                }
                for h in hits
                if h.s2_id
            ],
            "hint": "Pick a candidate s2_id and call add_seed(s2_id=...).",
        }

    return {
        "error": "missing_input",
        "hint": "Provide s2_id, doi, arxiv_id, paper_id, or title_query.",
    }


def add_seed(
    cfg: AppConfig,
    *,
    s2_id: str | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    title_query: str | None = None,
    paper_id: int | None = None,
    notes: str | None = None,
    enabled: bool = True,
    db: Database | None = None,
) -> dict[str, Any]:
    database = db or Database(cfg.db_path)
    resolved = resolve_seed_candidate(
        cfg,
        s2_id=s2_id,
        doi=doi,
        arxiv_id=arxiv_id,
        title_query=title_query,
        paper_id=paper_id,
        db=database,
    )
    if resolved.get("error"):
        return resolved
    if "candidates" in resolved:
        return resolved
    with database.session() as conn:
        seed = database.add_seed(
            conn,
            s2_id=resolved["s2_id"],
            doi=resolved.get("doi"),
            title=resolved.get("title"),
            year=resolved.get("year"),
            url=resolved.get("url"),
            notes=notes,
            enabled=enabled,
        )
        # Also upsert the seed paper itself into the corpus as a high-signal item.
        database.upsert_paper(
            conn,
            {
                "title": resolved.get("title") or "Seed paper",
                "doi": resolved.get("doi"),
                "year": resolved.get("year"),
                "url": resolved.get("url"),
                "source": "seed",
                "s2_id": resolved["s2_id"],
                "seed_hit": True,
                "score": 1.0,
            },
        )
    return {"ok": True, "seed": seed}


def list_seeds(
    cfg: AppConfig, *, enabled_only: bool = False, db: Database | None = None
) -> list[dict[str, Any]]:
    database = db or Database(cfg.db_path)
    with database.session() as conn:
        return database.list_seeds(conn, enabled_only=enabled_only)


def remove_seed(
    cfg: AppConfig,
    *,
    seed_id: int | None = None,
    s2_id: str | None = None,
    db: Database | None = None,
) -> dict[str, Any]:
    database = db or Database(cfg.db_path)
    with database.session() as conn:
        removed = database.remove_seed(conn, seed_id=seed_id, s2_id=s2_id)
    return {"ok": removed, "seed_id": seed_id, "s2_id": s2_id}


def set_seed_enabled(
    cfg: AppConfig, seed_id: int, enabled: bool, db: Database | None = None
) -> dict[str, Any]:
    database = db or Database(cfg.db_path)
    with database.session() as conn:
        seed = database.set_seed_enabled(conn, seed_id, enabled)
    if not seed:
        return {"error": "not_found", "seed_id": seed_id}
    return {"ok": True, "seed": seed}


def sync_config_seeds(cfg: AppConfig, db: Database | None = None) -> dict[str, Any]:
    """One-way import of legacy config.yaml seeds into the DB (no YAML writes)."""
    database = db or Database(cfg.db_path)
    with database.session() as conn:
        inserted = database.import_seed_ids(conn, list(cfg.seeds or []))
        total = len(database.list_seeds(conn))
    return {"imported": inserted, "seeds_total": total}


def active_seed_ids(cfg: AppConfig, db: Database | None = None) -> list[str]:
    database = db or Database(cfg.db_path)
    with database.session() as conn:
        # Prefer DB seeds; fall back to config only if DB empty.
        ids = database.enabled_seed_ids(conn)
        if ids:
            return ids
        if cfg.seeds:
            database.import_seed_ids(conn, list(cfg.seeds))
            return database.enabled_seed_ids(conn)
        return []
