from __future__ import annotations

import logging
from typing import Any, Callable

from my_lit_mcp.config import AppConfig
from my_lit_mcp.db import Database
from my_lit_mcp.ingest.sources import arxiv as arxiv_src
from my_lit_mcp.ingest.sources import openalex as openalex_src
from my_lit_mcp.ingest.sources import pubmed as pubmed_src
from my_lit_mcp.ingest.sources import s2 as s2_src
from my_lit_mcp.ingest.sources.unpaywall import resolve_oa_pdf
from my_lit_mcp.pdf import download_pdf, extract_text
from my_lit_mcp.rank import score_paper
from my_lit_mcp.seeds import active_seed_ids, sync_config_seeds

log = logging.getLogger(__name__)


def _resolve_pdf(cfg: AppConfig, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("oa_pdf_url"):
        return payload
    if payload.get("doi") and cfg.unpaywall_email:
        try:
            payload["oa_pdf_url"] = resolve_oa_pdf(
                payload.get("doi"),
                email=cfg.unpaywall_email,
                sleep_seconds=cfg.rate_limits.unpaywall_sleep_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Unpaywall failed for %s: %s", payload.get("doi"), exc)
    return payload


def _store_scored(db: Database, cfg: AppConfig, payload: dict[str, Any]) -> int:
    with db.session() as conn:
        paper_id = db.upsert_paper(conn, payload)
        paper = db.get_paper(conn, paper_id) or payload
        ft = db.get_fulltext(conn, paper_id)
        feedback = paper.get("feedback") or {}
        label = feedback.get("label") if isinstance(feedback, dict) else None
        seed_hit = bool(payload.get("seed_hit") or paper.get("seed_hit"))
        score = score_paper(
            paper,
            cfg.ranking,
            fulltext=(ft or {}).get("text"),
            feedback_label=label,
            seed_hit=seed_hit,
        )
        db.update_score(conn, paper_id, score, seed_hit=seed_hit)
        return paper_id


def parse_one_paper(db: Database, cfg: AppConfig, paper: dict[str, Any]) -> bool:
    paper_id = int(paper["id"])
    url = paper.get("oa_pdf_url")
    dest = cfg.pdf_cache_dir / f"{paper_id}.pdf"
    if not url:
        with db.session() as conn:
            db.set_fulltext(conn, paper_id, "", None, "no_pdf")
        return False
    try:
        download_pdf(url, dest)
        text, pages = extract_text(dest, max_pages=cfg.pdf.max_pages)
        status = "ok" if text else "error"
        with db.session() as conn:
            db.set_fulltext(conn, paper_id, text or "", pages, status, str(dest))
            row = db.get_paper(conn, paper_id) or paper
            feedback = row.get("feedback") or {}
            label = feedback.get("label") if isinstance(feedback, dict) else None
            score = score_paper(
                row,
                cfg.ranking,
                fulltext=text,
                feedback_label=label,
                seed_hit=bool(row.get("seed_hit")),
            )
            db.update_score(conn, paper_id, score, seed_hit=bool(row.get("seed_hit")))
        return status == "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("PDF parse failed for paper %s: %s", paper_id, exc)
        with db.session() as conn:
            db.set_fulltext(
                conn,
                paper_id,
                "",
                None,
                "error",
                str(dest) if dest.exists() else None,
            )
        return False


def run_parse(
    cfg: AppConfig, db: Database | None = None, limit: int | None = None
) -> dict[str, Any]:
    database = db or Database(cfg.db_path)
    max_n = limit if limit is not None else cfg.pdf.max_pdfs_per_run
    with database.session() as conn:
        papers = database.list_papers_needing_pdf(conn, max_n)
    ok = sum(1 for paper in papers if parse_one_paper(database, cfg, paper))
    return {"attempted": len(papers), "parsed_ok": ok}


def _fetch(
    cfg: AppConfig,
    db: Database,
    source: str,
    query: str,
    record_openalex_call: Callable[[], None],
):
    source = source.lower().strip()
    if source == "arxiv":
        return arxiv_src.search_arxiv(
            query, sleep_seconds=cfg.rate_limits.arxiv_sleep_seconds
        )
    if source in {"pubmed", "ncbi"}:
        return pubmed_src.search_pubmed(
            query,
            api_key=cfg.ncbi_api_key,
            sleep_seconds=cfg.rate_limits.pubmed_sleep_seconds,
        )
    if source in {"s2", "semantic_scholar", "semanticscholar"}:
        return s2_src.search_s2(
            query,
            api_key=cfg.semantic_scholar_api_key,
            sleep_seconds=cfg.rate_limits.s2_sleep_seconds,
        )
    if source == "openalex":
        with db.session() as conn:
            used = db.get_api_usage(conn, "openalex")
        return openalex_src.search_openalex(
            query,
            api_key=cfg.openalex_api_key,
            sleep_seconds=cfg.rate_limits.openalex_sleep_seconds,
            calls_used_today=used,
            max_calls_per_day=cfg.openalex.max_search_calls_per_day,
            record_call=record_openalex_call,
        )
    raise ValueError(f"Unknown source: {source}")


def run_ingest(cfg: AppConfig, db: Database | None = None) -> dict[str, Any]:
    database = db or Database(cfg.db_path)
    cfg.pdf_cache_dir.mkdir(parents=True, exist_ok=True)
    openalex_calls = 0

    def record_openalex_call() -> None:
        nonlocal openalex_calls
        with database.session() as conn:
            database.increment_api_usage(conn, "openalex", 1)
        openalex_calls += 1

    with database.session() as conn:
        run_id = database.start_run(conn)

    seen = 0
    upserted = 0
    errors: list[str] = []

    # Prefer DB-managed seeds; import any leftover config.yaml seeds once.
    sync_config_seeds(cfg, database)
    seed_ids = active_seed_ids(cfg, database)

    for seed in seed_ids:
        try:
            recs = s2_src.recommendations_for_seed(
                seed,
                api_key=cfg.semantic_scholar_api_key,
                sleep_seconds=cfg.rate_limits.s2_sleep_seconds,
            )
            for rec in recs:
                seen += 1
                payload = _resolve_pdf(cfg, rec.as_dict())
                payload["seed_hit"] = True
                _store_scored(database, cfg, payload)
                upserted += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"seed {seed}: {exc}")

    for query in cfg.queries:
        if not query.enabled:
            continue
        try:
            records = _fetch(cfg, database, query.source, query.query, record_openalex_call)
        except openalex_src.OpenAlexBudgetExceeded as exc:
            errors.append(str(exc))
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{query.name}: {exc}")
            continue
        for rec in records:
            seen += 1
            payload = _resolve_pdf(cfg, rec.as_dict())
            _store_scored(database, cfg, payload)
            upserted += 1

    pdfs_parsed = 0
    if cfg.pdf.parse_on_ingest:
        pdfs_parsed = int(run_parse(cfg, database)["parsed_ok"])

    with database.session() as conn:
        database.finish_run(
            conn,
            run_id,
            status="ok" if not errors else "ok_with_errors",
            papers_seen=seen,
            papers_upserted=upserted,
            pdfs_parsed=pdfs_parsed,
            openalex_calls=openalex_calls,
            detail={"errors": errors[:50]},
        )

    return {
        "run_id": run_id,
        "papers_seen": seen,
        "papers_upserted": upserted,
        "pdfs_parsed": pdfs_parsed,
        "openalex_calls": openalex_calls,
        "errors": errors,
    }
