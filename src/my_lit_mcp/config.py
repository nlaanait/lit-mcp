from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MARKER_NAME = ".my-lit-path"
DEFAULT_DATA_DIRNAME = ".my-lit"


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def example_config_path() -> Path:
    return package_root() / "config.example.yaml"


def _read_marker(marker: Path) -> Path | None:
    try:
        text = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    # First non-empty, non-comment line is the absolute data dir.
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        return Path(line).expanduser().resolve()
    return None


def find_project_marker(start: Path | None = None) -> Path | None:
    """Walk up from start (cwd) and also check the package root for `.my-lit-path`."""
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add_chain(root: Path) -> None:
        cur = root.resolve()
        while True:
            if cur not in seen:
                seen.add(cur)
                candidates.append(cur / MARKER_NAME)
            if cur.parent == cur:
                break
            cur = cur.parent

    add_chain(start or Path.cwd())
    add_chain(package_root())

    for marker in candidates:
        if marker.is_file():
            return marker
    return None


def find_local_data_dir(start: Path | None = None) -> Path | None:
    """Find a conventional `<project>/.my-lit` data dir with config.yaml."""
    seen: set[Path] = set()

    def walk(root: Path):
        cur = root.resolve()
        while True:
            if cur not in seen:
                seen.add(cur)
                candidate = cur / DEFAULT_DATA_DIRNAME
                if (candidate / "config.yaml").is_file():
                    yield candidate
            if cur.parent == cur:
                break
            cur = cur.parent

    for path in walk(start or Path.cwd()):
        return path
    for path in walk(package_root()):
        return path
    return None


def write_project_marker(data_dir: Path, project_root: Path | None = None) -> Path:
    """Persist the chosen data dir once so CLI/MCP resolve the same project paths."""
    root = (project_root or Path.cwd()).resolve()
    marker = root / MARKER_NAME
    marker.write_text(
        f"# Project-scoped my-lit data directory (set by `my-lit init`)\n{data_dir.resolve()}\n",
        encoding="utf-8",
    )
    return marker


def default_data_dir() -> Path:
    """Resolve the project data directory (not a global Application Support path).

    Order:
    1. MY_LIT_DATA_DIR
    2. Path recorded in a `.my-lit-path` marker (from `my-lit init`)
    3. Conventional `<project>/.my-lit` if it already has config.yaml
    4. Error — user must run init once with a path
    """
    if os.environ.get("MY_LIT_DATA_DIR"):
        return Path(os.environ["MY_LIT_DATA_DIR"]).expanduser().resolve()
    marker = find_project_marker()
    if marker is not None:
        data_dir = _read_marker(marker)
        if data_dir is not None:
            return data_dir
    local = find_local_data_dir()
    if local is not None:
        return local
    raise FileNotFoundError(
        "No project data directory configured. "
        "Call MCP ensure_workspace(project_root=...) or run "
        "`my-lit init --data-dir <path>` once."
    )


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
        raise FileNotFoundError(f"Config not found: {path}. Run `my-lit init --data-dir <path>` first.")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    data_dir = path.parent
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


def init_workspace(
    data_dir: Path | None = None,
    config_path: Path | None = None,
    force: bool = False,
    project_root: Path | None = None,
) -> AppConfig:
    """Create project-scoped config/DB/PDF dirs and record the path in `.my-lit`.

    `data_dir` is required unless `MY_LIT_DATA_DIR` is already set (tests/CI).
    """
    root = (project_root or Path.cwd()).resolve()
    if data_dir is not None:
        resolved = data_dir.expanduser().resolve()
    elif os.environ.get("MY_LIT_DATA_DIR"):
        resolved = Path(os.environ["MY_LIT_DATA_DIR"]).expanduser().resolve()
    else:
        raise ValueError(
            "Choose a project data directory once: `my-lit init --data-dir <path>` "
            f"(suggested: {root / DEFAULT_DATA_DIRNAME})"
        )

    resolved.mkdir(parents=True, exist_ok=True)
    os.environ["MY_LIT_DATA_DIR"] = str(resolved)

    if config_path is not None:
        dest = config_path.expanduser().resolve()
    elif os.environ.get("MY_LIT_CONFIG"):
        dest = Path(os.environ["MY_LIT_CONFIG"]).expanduser().resolve()
    else:
        dest = resolved / "config.yaml"

    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or force:
        shutil.copyfile(example_config_path(), dest)

    write_project_marker(resolved, project_root=root)

    cfg = load_config(dest)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.pdf_cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def workspace_is_ready(data_dir: Path | None = None) -> bool:
    """True when the resolved data dir already has a config.yaml."""
    try:
        path = (data_dir or default_data_dir()) / "config.yaml"
    except FileNotFoundError:
        return False
    return path.is_file()


def ensure_workspace(
    project_root: Path | None = None,
    data_dir: Path | None = None,
    force: bool = False,
) -> tuple[AppConfig, bool]:
    """Idempotently create project-scoped data if missing.

    Returns ``(config, created)`` where ``created`` is True when init ran.

    Resolution:
    1. Explicit ``data_dir``
    2. ``project_root / .my-lit`` when ``project_root`` is given
    3. Existing ``MY_LIT_DATA_DIR`` / marker / conventional ``.my-lit``
    4. ``cwd / .my-lit`` as last resort
    """
    root = (project_root or Path.cwd()).resolve()

    if data_dir is not None:
        resolved = data_dir.expanduser().resolve()
    elif project_root is not None:
        resolved = root / DEFAULT_DATA_DIRNAME
    elif os.environ.get("MY_LIT_DATA_DIR"):
        resolved = Path(os.environ["MY_LIT_DATA_DIR"]).expanduser().resolve()
    else:
        try:
            resolved = default_data_dir()
        except FileNotFoundError:
            resolved = root / DEFAULT_DATA_DIRNAME

    config_path = resolved / "config.yaml"
    if config_path.is_file() and not force:
        os.environ["MY_LIT_DATA_DIR"] = str(resolved)
        write_project_marker(resolved, project_root=root)
        return load_config(config_path), False

    cfg = init_workspace(data_dir=resolved, force=force, project_root=root)
    return cfg, True
