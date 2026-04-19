# Changelog

All notable changes to ringwood are recorded here. Format is loose
[Keep a Changelog](https://keepachangelog.com/); versioning is SemVer-ish
during the pre-1.0 period.

## [0.1.0] — 2026-04-19

Initial working release. Everything below is shipped and tested.

### Added
- **ringwood** Python library
  - `Page` model with bitemporal metadata (`valid_at`, `invalid_at`,
    `last_confirmed`), reinforcement counters, and provenance
  - `LocalFSStorage` adapter (MinIO + Git adapters follow)
  - `Fts5Index` with **trigram tokenizer** for Korean/Japanese/Chinese
    morphology-agnostic search
  - Compounding engine — 5 modules, each with an offline deterministic
    fallback and a live LLM path:
      - `classifier` (Haiku 4.5)   — worthiness filter
      - `contextualize` (Haiku 4.5) — Contextual Retrieval prefix with
        prompt caching
      - `decision` (Sonnet 4.6)   — ADD / UPDATE / DELETE / NOOP
      - `rewriter` (Sonnet 4.6)   — page rewrite on UPDATE
      - `lint`                    — broken links, stale, orphans
  - Public API — `search / get / ingest / record_answer / lint / stats`
  - `.env` auto-loading with real-env-wins precedence
- **ringwood-mcp** — MCP server exposing ringwood
  - 6 tools: `search_wiki`, `get_article`, `ingest_source`, `record_answer`,
    `list_recent_changes`, `lint_wiki`
  - 2 resource templates: `wiki://article/{page_id}`, `wiki://log`
  - Inline citation footer in `search_wiki` responses
  - stdio transport (streamable-HTTP in Phase 3)
  - `ringwood-capture` Stop-hook target for Claude Code
  - `ringwood-cli` visibility commands — `stats / timeline / diff / list /
    show / lint`
- **npm-launcher** — `npx ringwood` with subcommands
  - `init` auto-patches `~/.claude.json`, backs up first, seeds `.env`
    with `chmod 600`
  - `--with-hook` / `--no-hook` for Stop-hook opt-in
  - passthrough for every CLI subcommand
  - `doctor` diagnostic
- **bootstrap.sh + Makefile** — one-command install
- **Test suites**
  - 21 offline tests (stub LLM fallback path)
  - 24 live tests (real Anthropic API): golden scenarios + classifier
    precision + prompt caching + MCP stdio E2E
  - A/B answer-quality test: bare Claude vs Claude+wiki, 4/5 wins for wiki

### Bug discoveries during live testing (all fixed in this release)
- FTS5 `unicode61` tokenizer strandled Korean 조사 variants → switched to
  `trigram`
- FTS5 query escape quoted punctuation into literal phrase matches → strip
  noise, OR-combine tokens
- DELETE decisions lost new information → refactored to Graphiti-style
  supersede (invalidate old + write new + link)
- Single-angle candidate retrieval missed semantic neighbors → multi-angle
  union (title + first-line + body excerpt)

### Known limitations
- Korean-primary golden set; English/code-heavy behavior less rigorously
  tested
- No vector search; purely BM25 recall can miss semantic paraphrases
  (see A/B report, scenario Q4)
- No agentic multi-round retrieval — one search per answer
- No HTTP transport (Phase 3)
