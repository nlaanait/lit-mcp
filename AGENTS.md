# Agent Guidelines: Literature Pipeline & MCP Usage

## Core Directive: Local Literature MCP First

When responding to queries regarding **custom literature search, paper discovery, literature review, seed tracking, or paper full-text analysis**, you **MUST rely on the `my-lit-pipeline` MCP server first** before consulting external sources, web search, or general literature databases.

The local database (`papers.db`) and PDF cache contain curated, scored, and full-text parsed literature specifically accumulated for this workspace.

---

## Bootstrap: ensure project data exists

Literature data is **project-scoped** under `.my-lit/` (not a global Application Support path).

**Before any other literature MCP tool**, call:

```text
ensure_workspace(project_root=<absolute path to the current workspace/repo>)
```

- If `.my-lit` (config + DB + pdfs) is missing, this **creates** it.
- If it already exists, this is a no-op (`created: false`).
- Always pass the **host project** path (the repo the user is working in), not the `my-lit-mcp` package path unless that *is* the project.
- If another tool returns `error: workspace_not_ready`, call `ensure_workspace` with `project_root` and retry.

Do **not** ask the user to run `my-lit init` manually when you can call `ensure_workspace`.

---

## Tool Selection & Usage Hierarchy

### 1. Searching & Inspecting Local Literature
Always query the local corpus first when asked about relevant literature, techniques, or topics:
- **`ensure_workspace(project_root, data_dir, force)`**: Create `.my-lit` if missing (see Bootstrap above).
- **`search_local(query, source, label, since, limit)`**: Primary tool to search titles, abstracts, and full text in the local SQLite corpus.
- **`search_fulltext(query, source, limit)`**: Use when looking for specific methodologies, phrases, benchmarks, or details within parsed PDF body text.
- **`get_paper(paper_id)`**: Inspect complete metadata, abstract, score, and feedback status for a specific local paper.
- **`get_fulltext(paper_id, max_chars)`**: Read the extracted text of a local paper's PDF.
- **`must_read(limit)`**: Retrieve papers marked with high relevance scores or labeled as `must_read`.
- **`similar_to(paper_id, limit)`**: Find locally stored papers sharing title/keyword similarities with a given paper.
- **`new_since(since, limit)`**: Check papers ingested after a given ISO timestamp.

### 2. Managing Seeds & Ingest Configuration
Seeds drive recommendations during pipeline ingestion runs:
- **`list_seeds(enabled_only)`**: View all active or configured seed papers in the database.
- **`resolve_seed(s2_id, doi, arxiv_id, title_query, paper_id)`**: Resolve candidate metadata without saving. Always use this to verify or disambiguate a paper before adding it.
- **`add_seed(...)`**: Save or update a seed paper in the DB (upserts by `s2_id`).
- **`remove_seed(seed_id, s2_id)`**: Delete a seed.
- **`set_seed_enabled(seed_id, enabled)`**: Enable or disable a seed without deleting it.
- **`list_queries()`**: Inspect configured search queries.

> **CRITICAL RULE**: Seeds are managed strictly in SQLite via the MCP tools (`add_seed`, `remove_seed`, `set_seed_enabled`). Never ask the user to edit `config.yaml` to manage seeds.

### 3. Feedback & Pipeline Monitoring
- **`mark_feedback(paper_id, label, notes)`**: Update paper feedback labels (`relevant`, `not_relevant`, `must_read`). Always record feedback when the user indicates interest or disinterest in a paper.
- **`pipeline_status()`**: Check database counts, last ingestion run, and daily OpenAlex call quotas.

### 4. Optional API / ingest env vars
These are optional but improve ingest rate limits and OA PDF resolution. They may be set in the shell and/or the MCP server `env` block (e.g. `.mcp.json`):

| Env var | Effect when missing |
|---------|---------------------|
| `UNPAYWALL_EMAIL` | OA PDF URL resolution via Unpaywall is skipped |
| `OPENALEX_API_KEY` | OpenAlex queries cannot run |
| `SEMANTIC_SCHOLAR_API_KEY` | S2 works anonymously but is more likely to hit 429s |
| `NCBI_API_KEY` | PubMed runs at the lower unauthenticated rate |

**When any of these are unset**, tell the user explicitly which ones are missing and what that limits (do not silently assume keys are configured). Suggest adding them to the MCP `env` block and the shell profile so CLI ingest and MCP share the same values.

---

## Fallback & External Search Protocol

You should only reach out to external sources (e.g., arXiv, PubMed, Europe PMC, or Web Search) if:
1. `search_local` and `search_fulltext` return zero relevant matches or insufficient coverage for the user's specific query.
2. The user explicitly asks to fetch new external literature or update the pipeline.

When valuable new papers are identified from external searches, recommend adding them to the local pipeline using `resolve_seed` and `add_seed` so they will be ingested, scored, and parsed locally on future pipeline runs.

---

## Proactive Follow-on Actions & Lifecycle Maintenance

Whenever you complete a literature task, search, or review, **always proactively propose concrete follow-on actions** to keep the local corpus fresh, well-indexed, and well-scored:

### 1. After Finding Relevant Papers (Local or External)
- **Seed Promotion**: Propose adding high-signal papers as seeds using `add_seed(doi=...)` or `add_seed(s2_id=...)` so the pipeline automatically discovers related work in subsequent runs.
- **Relevance Feedback**: Prompt the user to tag candidate papers with `mark_feedback(paper_id, label='relevant' | 'must_read' | 'not_relevant')` to calibrate local ranking weights.
- **Deep Reading**: Offer to extract and inspect the full body text via `get_fulltext(paper_id)` for papers with parsed PDFs.
- **Related Papers**: Propose exploring local cluster neighbors with `similar_to(paper_id)`.

### 2. After Modifying Seeds (Adding, Enabling, Disabling, Removing)
- **Ingestion Cycle**: Propose running an ingest cycle (`uv run my-lit ingest`) to fetch new candidate recommendations driven by the updated seed set.
- **Full-Text Parsing / Re-indexing**: Propose running `uv run my-lit parse` to backfill and extract text from newly downloaded open-access PDFs.

### 3. After Stale or Zero-Result Searches
- **Pipeline Refresh**: If a local search yields few or outdated results, propose checking `pipeline_status()`, verifying active queries with `list_queries()`, or running `uv run my-lit ingest` to refresh the corpus.
- **Query / Seed Expansion**: Suggest adding new search queries or seed DOIs/arXiv IDs to cover the missing subfield.
