# my-lit-mcp

Own a free literature pipeline: ingest from Semantic Scholar, PubMed, arXiv, and OpenAlex (free daily allowance), store in project-local SQLite, download OA PDFs, extract full text with PyMuPDF, rank with your rules, and expose it to any MCP host over stdio.

## Setup

```bash
brew install uv
cd my-lit-mcp
uv sync

# optional free keys (never required for arXiv)
export UNPAYWALL_EMAIL=you@example.com
export OPENALEX_API_KEY=...          # free; stay within daily free search allowance
export SEMANTIC_SCHOLAR_API_KEY=...  # free; improves rate limits
export NCBI_API_KEY=...              # free; improves PubMed rate limits

# choose a project data dir once (prompts if omitted on a TTY)
uv run my-lit init --data-dir .my-lit

# wire MCP once at user/global scope in your MCP host (recommended):
# copy mcp.example.json into the host's user MCP config, then edit:
#   absolute uv path, --directory = this my-lit-mcp install, optional API keys
# omit MY_LIT_DATA_DIR (or set it via host workspace interpolation); agents call
# ensure_workspace(project_root=...) so each project uses its own .my-lit/

# optionally edit queries in <data-dir>/config.yaml; manage seeds via MCP, not YAML
uv run my-lit ingest
uv run my-lit status
```

## Project data (not global)

Config, DB, and PDFs live under the directory you pass to `init`.

`my-lit init --data-dir <path>`:

1. Creates `<data-dir>/config.yaml`, `papers.db`, and `pdfs/`
2. Writes `.my-lit-path` in the project root so later CLI runs resolve the same directory

| Path | Role |
|------|------|
| `<data-dir>/config.yaml` | Queries, ranking, rate limits |
| `<data-dir>/papers.db` | Papers, seeds, feedback, full text |
| `<data-dir>/pdfs/` | OA PDF cache |
| `.my-lit-path` | Marker pointing at `<data-dir>` (gitignored) |

Suggested: `./.my-lit` inside the repo (gitignored).

**Resolution order:** `MY_LIT_DATA_DIR` → `.my-lit-path` → conventional `./.my-lit` if it already has `config.yaml`. Optional overrides: `MY_LIT_CONFIG`, `MY_LIT_DB`, `MY_LIT_PDF_DIR`.

## CLI

| Command | Purpose |
|---------|---------|
| `my-lit init --data-dir <path>` | Create project-scoped config + DB + PDF cache; record path in `.my-lit-path` |
| `my-lit ingest` | Fetch queries/seeds, Unpaywall enrich, score, optionally parse PDFs |
| `my-lit parse` | Backfill OA PDF download + text extraction |
| `my-lit status` | Counts, OpenAlex calls today, last run |

Schedule ingest with the LaunchAgent example in [`launchd/com.my-lit.ingest.plist.example`](launchd/com.my-lit.ingest.plist.example) (set `MY_LIT_DATA_DIR` there too).

## MCP registration

**Intended split:** user-/global-scoped MCP server + project-scoped literature DB.

| Concern | Where | Why |
|---------|-------|-----|
| MCP server process | Your MCP host’s **user/global** config | One install of `my-lit-mcp`, available in every workspace |
| Papers / seeds / PDFs | `<host-project>/.my-lit/` | Each project keeps its own corpus |

Commit only [`mcp.example.json`](mcp.example.json). Absolute paths and API keys belong in local (gitignored) MCP config—not in the repo. Hosts differ on file location (user vs project vs UI); use the host’s docs. Common shapes: user/global `mcp.json`, project `.mcp.json`, or an IDE settings UI.

### Recommended: user-/global-scoped MCP

1. Copy [`mcp.example.json`](mcp.example.json) into your host’s **user/global** MCP config (not into every project).
2. Edit:
   - `command` to an absolute `uv` path if `uv` is not on the host’s default PATH (e.g. `~/.local/bin/uv`)
   - `args` `--directory` to this **my-lit-mcp install** (the package that runs the server)—not the host project
   - Optional API env vars (same values as your shell)
3. Prefer **omitting** `MY_LIT_DATA_DIR` in user/global config. Agents call `ensure_workspace(project_root=<absolute host project path>)`, which creates/binds `<project>/.my-lit`.
4. If your host supports workspace-path interpolation in env values, you may set `MY_LIT_DATA_DIR` to that project’s `.my-lit` instead (still per open workspace—never a single hard-coded project path).

Do **not** hard-code one project’s absolute `.my-lit` path in user/global MCP config—that pins every workspace to a single DB.

If the same server name is also defined at project scope, many hosts let **project config win**. Prefer only the user/global entry for this layout.

Reload or restart MCP in your host after editing config.

```bash
uv run my-lit-mcp
```

MCP tools: `ensure_workspace`, `list_queries`, `list_seeds` / `resolve_seed` / `add_seed` / `remove_seed` / `set_seed_enabled`, `search_local`, `search_fulltext`, `get_paper`, `get_fulltext`, `new_since`, `must_read`, `similar_to`, `mark_feedback`, `pipeline_status`.

Agents should call `ensure_workspace(project_root=<host workspace>)` first; it creates that project’s `.my-lit` when missing. See [`AGENTS.md`](AGENTS.md).

### Optional: project-only MCP

For a single-repo install, copy `mcp.example.json` into that project’s MCP config (e.g. `.mcp.json` or the host’s project MCP path). You may set `MY_LIT_DATA_DIR` to that project’s `.my-lit` absolute path when the config will never be shared across projects.

## Seed management (MCP, not config files)

Seeds live in SQLite. Agents should manage them via MCP.

| Tool | Purpose |
|------|---------|
| `list_seeds` | Show saved seeds (`enabled_only` optional) |
| `resolve_seed` | Look up metadata by `s2_id`, `doi`, `arxiv_id`, local `paper_id`, or `title_query` (candidates) without saving |
| `add_seed` | Save a seed (same lookup fields as resolve); upserts by `s2_id` |
| `remove_seed` | Delete by `seed_id` or `s2_id` |
| `set_seed_enabled` | Disable/enable without deleting |

On `my-lit ingest`, enabled DB seeds drive Semantic Scholar recommendations.

## API keys (all free)

| Env var | Required? | Why set it |
|---------|-----------|------------|
| `UNPAYWALL_EMAIL` | For OA PDF resolution | Unpaywall requires an email; no key signup |
| `OPENALEX_API_KEY` | Only if an OpenAlex query is enabled | Free key; see OpenAlex rule below |
| `SEMANTIC_SCHOLAR_API_KEY` | No | Avoids shared-pool **429**s; higher dedicated rate limits |
| `NCBI_API_KEY` | No | PubMed E-utilities ~3 req/s without a key → ~10 req/s with one |

**Semantic Scholar:** request a free API key from [Semantic Scholar’s API page](https://www.semanticscholar.org/product/api). This project sends it as `x-api-key` on paper search and seed recommendations. Anonymous calls often work briefly, then throttle.

**NCBI / PubMed:** create a free NCBI account and generate an API key under account settings. Pass it as `NCBI_API_KEY`; it is forwarded to `esearch` / `efetch` as `api_key`.

Put the same env vars in your shell profile **and** in the MCP server `env` block so CLI ingest and the MCP server share them. If any are unset, ingest still runs where possible, with the limits in the table above.

## OpenAlex free-tier rule

OpenAlex search uses a free API key and a hard daily call cap (`openalex.max_search_calls_per_day`, default 800). The pipeline stops OpenAlex for the day when the cap or HTTP 429 is hit.  

## Ranking

`score = 0.6 * seed_hit + 0.3 * keyword_hit + 0.1 * recency`, then adjust from feedback labels (`relevant` / `not_relevant` / `must_read`). Keyword matching can include PDF full text when `match_fulltext: true`.

## Tests

```bash
uv run pytest -q
```
