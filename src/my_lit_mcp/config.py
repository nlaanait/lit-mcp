from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

APP_NAME = "my-lit-mcp"


def default_data_dir() -> Path:
    if os.environ.get("MY_LIT_DATA_DIR"):
        return Path(os.environ["MY_LIT_DATA_DIR"]).expanduser().resolve()
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if system == "Windows":
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / APP_NAME
    return home / ".local" / "share" / APP_NAME


@dataclass
class QueryConfig:
    name: str
    source: str
    query: str
    enabled: bool = True


@dataclass
class RankingConfig:
    include_terms: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    must_read_threshold: float = 0.55
    weight_seed: float = 0.6
    weight_keyword: float = 0.3
    weight_recency: float = 0.1
    match_fulltext: bool = True


@dataclass
class PdfConfig:
    parse_on_ingest: bool = True
    max_pdfs_per_run: int = 25
    max_pages: int = 40


@dataclass
class OpenAlexConfig:
    max_search_calls_per_day: int = 800


@dataclass
class RateLimits:
    s2_sleep_seconds: float = 1.1
    pubmed_sleep_seconds: float = 0.35
    arxiv_sleep_seconds: float = 3.0
    openalex_sleep_seconds: float = 0.2
    unpaywall_sleep_seconds: float = 0.2


@dataclass
class AppConfig:
    config_path: Path
    db_path: Path
    pdf_cache_dir: Path
    queries: list[QueryConfig]
    seeds: list[str]
    ranking: RankingConfig
    pdf: PdfConfig
    openalex: OpenAlexConfig
    rate_limits: RateLimits

    @property
    def unpaywall_email(self) -> str:
        return os.environ.get("UNPAYWALL_EMAIL", "").strip()

    @property
    def openalex_api_key(self) -> str:
        return os.environ.get("OPENALEX_API_KEY", "").strip()

    @property
    def semantic_scholar_api_key(self) -> str:
        return os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()

    @property
    def ncbi_api_key(self) -> str:
        return os.environ.get("NCBI_API_KEY", "").strip()


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def example_config_path() -> Path:
    return package_root() / "config.example.yaml"


def resolve_config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    if os.environ.get("MY_LIT_CONFIG"):
        return Path(os.environ["MY_LIT_CONFIG"]).expanduser().resolve()
    return default_data_dir() / "config.yaml"


def _path_or_default(value: Any, default: Path) -> Path:
    if value in (None, "", "null"):
        return default
    return Path(str(value)).expanduser().resolve()


def load_config(config_path: Path | None = None) -> AppConfig:
    path = resolve_config_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}. Run `my-lit init` first.")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    data_dir = default_data_dir()
    db_default = (
        Path(os.environ["MY_LIT_DB"]).expanduser().resolve()
        if os.environ.get("MY_LIT_DB")
        else data_dir / "papers.db"
    )
    pdf_default = (
        Path(os.environ["MY_LIT_PDF_DIR"]).expanduser().resolve()
        if os.environ.get("MY_LIT_PDF_DIR")
        else data_dir / "pdfs"
    )

    queries = [
        QueryConfig(
            name=str(item.get("name", f"query_{idx}")),
            source=str(item.get("source", "")).lower().strip(),
            query=str(item.get("query", "")),
            enabled=bool(item.get("enabled", True)),
        )
        for idx, item in enumerate(raw.get("queries") or [])
    ]
    ranking_raw = raw.get("ranking") or {}
    pdf_raw = raw.get("pdf") or {}
    oa_raw = raw.get("openalex") or {}
    rl_raw = raw.get("rate_limits") or {}

    return AppConfig(
        config_path=path,
        db_path=_path_or_default(raw.get("db_path"), db_default),
        pdf_cache_dir=_path_or_default(raw.get("pdf_cache_dir"), pdf_default),
        queries=queries,
        seeds=[str(s) for s in (raw.get("seeds") or [])],
        ranking=RankingConfig(
            include_terms=list(ranking_raw.get("include_terms") or []),
            exclude_terms=list(ranking_raw.get("exclude_terms") or []),
            must_read_threshold=float(ranking_raw.get("must_read_threshold", 0.55)),
            weight_seed=float(ranking_raw.get("weight_seed", 0.6)),
            weight_keyword=float(ranking_raw.get("weight_keyword", 0.3)),
            weight_recency=float(ranking_raw.get("weight_recency", 0.1)),
            match_fulltext=bool(ranking_raw.get("match_fulltext", True)),
        ),
        pdf=PdfConfig(
            parse_on_ingest=bool(pdf_raw.get("parse_on_ingest", True)),
            max_pdfs_per_run=int(pdf_raw.get("max_pdfs_per_run", 25)),
            max_pages=int(pdf_raw.get("max_pages", 40)),
        ),
        openalex=OpenAlexConfig(
            max_search_calls_per_day=int(oa_raw.get("max_search_calls_per_day", 800)),
        ),
        rate_limits=RateLimits(
            s2_sleep_seconds=float(rl_raw.get("s2_sleep_seconds", 1.1)),
            pubmed_sleep_seconds=float(rl_raw.get("pubmed_sleep_seconds", 0.35)),
            arxiv_sleep_seconds=float(rl_raw.get("arxiv_sleep_seconds", 3.0)),
            openalex_sleep_seconds=float(rl_raw.get("openalex_sleep_seconds", 0.2)),
            unpaywall_sleep_seconds=float(rl_raw.get("unpaywall_sleep_seconds", 0.2)),
        ),
    )


def init_workspace(config_path: Path | None = None, force: bool = False) -> AppConfig:
    data_dir = default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = resolve_config_path(config_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or force:
        shutil.copyfile(example_config_path(), dest)
    cfg = load_config(dest)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.pdf_cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg
