from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from my_lit_mcp.config import init_workspace, load_config
from my_lit_mcp.db import Database
from my_lit_mcp.ingest.runner import run_ingest, run_parse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="my-lit", description="Own your literature pipeline")
    parser.add_argument("--config", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Create config/DB/PDF dirs")
    init_p.add_argument("--force", action="store_true")
    sub.add_parser("ingest", help="Fetch, enrich, score, optionally parse PDFs")
    parse_p = sub.add_parser("parse", help="Backfill OA PDF parsing")
    parse_p.add_argument("--limit", type=int, default=None)
    sub.add_parser("status", help="Show pipeline status")

    args = parser.parse_args(argv)

    if args.command == "init":
        cfg = init_workspace(args.config, force=args.force)
        Database(cfg.db_path)
        print(
            json.dumps(
                {
                    "config": str(cfg.config_path),
                    "db": str(cfg.db_path),
                    "pdf_cache": str(cfg.pdf_cache_dir),
                },
                indent=2,
            )
        )
        return 0

    cfg = load_config(args.config)
    db = Database(cfg.db_path)

    if args.command == "ingest":
        print(json.dumps(run_ingest(cfg, db), indent=2))
        return 0
    if args.command == "parse":
        print(json.dumps(run_parse(cfg, db, limit=args.limit), indent=2))
        return 0
    if args.command == "status":
        with db.session() as conn:
            print(json.dumps(db.status_summary(conn), indent=2, default=str))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
