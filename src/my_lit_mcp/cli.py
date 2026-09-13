from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from my_lit_mcp.config import DEFAULT_DATA_DIRNAME, MARKER_NAME, init_workspace, load_config
from my_lit_mcp.db import Database
from my_lit_mcp.ingest.runner import run_ingest, run_parse


def _prompt_data_dir(project_root: Path) -> Path:
    suggested = project_root / DEFAULT_DATA_DIRNAME
    if not sys.stdin.isatty():
        raise SystemExit(
            "Pass --data-dir <path> to choose where this project's config, DB, and PDFs live "
            f"(suggested: {suggested})"
        )
    raw = input(f"Project data directory [{suggested}]: ").strip()
    return Path(raw).expanduser() if raw else suggested


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="my-lit", description="Own your literature pipeline")
    parser.add_argument("--config", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Create project-scoped config/DB/PDF dirs")
    init_p.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Project data directory for config.yaml, papers.db, and pdfs/ (recorded in .my-lit)",
    )
    init_p.add_argument("--force", action="store_true")
    sub.add_parser("ingest", help="Fetch, enrich, score, optionally parse PDFs")
    parse_p = sub.add_parser("parse", help="Backfill OA PDF parsing")
    parse_p.add_argument("--limit", type=int, default=None)
    sub.add_parser("status", help="Show pipeline status")

    args = parser.parse_args(argv)

    if args.command == "init":
        project_root = Path.cwd()
        data_dir = args.data_dir
        if data_dir is None and not os.environ.get("MY_LIT_DATA_DIR"):
            data_dir = _prompt_data_dir(project_root)
        cfg = init_workspace(
            data_dir=data_dir,
            config_path=args.config,
            force=args.force,
            project_root=project_root,
        )
        Database(cfg.db_path)
        print(
            json.dumps(
                {
                    "config": str(cfg.config_path),
                    "db": str(cfg.db_path),
                    "pdf_cache": str(cfg.pdf_cache_dir),
                    "data_dir": str(cfg.config_path.parent),
                    "marker": str(project_root / MARKER_NAME),
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
