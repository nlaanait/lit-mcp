# my-lit-mcp

Own a free literature pipeline on your Mac: ingest from Semantic Scholar, PubMed, arXiv, and OpenAlex (free daily allowance), store in local SQLite, download OA PDFs, extract full text with PyMuPDF, rank with your rules, and expose it to any MCP host over stdio.

## Mac setup

```bash
brew install uv
cd my-lit-mcp
uv sync

# optional free keys (never required for arXiv)
export UNPAYWALL_EMAIL=you@example.com
export OPENALEX_API_KEY=...          # free; stay within daily free search allowance
export SEMANTIC_SCHOLAR_API_KEY=...  # free; improves rate limits
export NCBI_API_KEY=...              # free; improves PubMed rate limits

uv run my-lit init
# optionally edit queries in config.yaml; manage seeds via MCP (add_seed), not YAML
uv run my-lit ingest
uv run my-lit status
```

Data defaults (macOS):

- Config: `~/Library/Application Support/my-lit-mcp/config.yaml`
- DB: `~/Library/Application Support/my-lit-mcp/papers.db`
- PDFs: `~/Library/Application Support/my-lit-mcp/pdfs`

Override with `MY_LIT_CONFIG`, `MY_LIT_DB`, `MY_LIT_PDF_DIR`, or `MY_LIT_DATA_DIR`.

## CLI

| Command | Purpose |
|---------|---------|
| `my-lit init` | Create config + DB + PDF cache |
| `my-lit ingest` | Fetch queries/seeds, Unpaywall enrich, score, optionally parse PDFs |
| `my-lit parse` | Backfill OA PDF download + text extraction |
| `my-lit status` | Counts, OpenAlex calls today, last run |

Schedule ingest with the LaunchAgent example in [`launchd/com.my-lit.ingest.plist.example`](launchd/com.my-lit.ingest.plist.example).

## Portable MCP registration

Copy [`mcp.example.json`](mcp.example.json) into Claude Desktop / Claude Code / VS Code / Windsurf (or any stdio MCP host). Replace absolute paths and env values. This is **not** Cursor-specific.

```bash
uv run my-lit-mcp
```

MCP tools:

- `list_queries`
- `list_seeds` / `resolve_seed` / `add_seed` / `remove_seed` / `set_seed_enabled`
- `search_local`
- `search_fulltext`
- `get_paper`
- `get_fulltext`
- `new_since`
- `must_read`
- `similar_to`
- `mark_feedback`
- `pipeline_status`

## Seed management (MCP, not config files)

Seeds live in SQLite. Agents should manage them via MCP—do **not** ask users to edit YAML for seeds.

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

Put the same env vars in your shell profile and in the `env` block of `mcp.example.json` so CLI ingest and the MCP server share them.

## OpenAlex free-tier rule

OpenAlex search uses a free API key and a hard daily call cap (`openalex.max_search_calls_per_day`, default 800). The pipeline stops OpenAlex for the day when the cap or HTTP 429 is hit. Do not enable prepaid OpenAlex billing.

## Ranking

`score = 0.6 * seed_hit + 0.3 * keyword_hit + 0.1 * recency`, then adjust from feedback labels (`relevant` / `not_relevant` / `must_read`). Keyword matching can include PDF full text when `match_fulltext: true`.

## Tests

```bash
uv run pytest -q
```
