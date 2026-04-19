# ringwood

Pure-Python core of [ringwood](https://github.com/ringwood/ringwood) —
a compounding knowledge wiki for Claude. Protocol-agnostic. The MCP server,
the npm launcher, and the LangChain adapter are all thin shells on top
of this library.

**See the main [README](https://github.com/ringwood/ringwood#readme)** for
the user-facing walkthrough, A/B quality numbers, and troubleshooting.
This file is the minimum a Python importer needs.

## Install

```bash
pip install ringwood
# or for embedding + reranker support:
pip install "ringwood[vector,rerank]"
```

## Quickstart

```python
from ringwood import Wiki

wiki = Wiki(root="~/my-wiki")              # LocalFS + SQLite FTS5
wiki.ingest(
    "Our team uses snake_case for filenames.",
    source_ref="team-convention.md",
)
hits = wiki.search("filename convention")
for h in hits:
    print(h.page_id, h.title, h.summary[:80])
```

Without an `ANTHROPIC_API_KEY`, engine calls fall back to deterministic
rules (regex classifier, simple decision heuristic). With one, Haiku 4.5
and Sonnet 4.6 do the work.

Put your key in `~/my-wiki/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Public API (stable within 0.x)

| Symbol | What it does |
|---|---|
| `Wiki(root, *, storage?, index?, llm?)` | Composition root |
| `Wiki.search(query, limit=10)` | Hybrid BM25 search, invalid pages excluded |
| `Wiki.get(page_id)` | Read a page as a `Page` object |
| `Wiki.ingest(text, *, source_ref, title=None, kind=..., tags=..., volatility=...)` | Route NEW_INFO through ADD/UPDATE/DELETE/NOOP |
| `Wiki.record_answer(question, answer, sources=None)` | Classifier-gated file |
| `Wiki.lint()` | Broken links, stale pages, orphans |
| `Wiki.stats(period='week')` | Growth summary |
| `Page` | Markdown + frontmatter, bitemporal |
| `StorageAdapter`, `LocalFSStorage`, `PageNotFound` | Pluggable storage |
| `IndexAdapter`, `Fts5Index`, `SearchHit` | Pluggable search |

## Writing a custom adapter

Any backend that implements the `StorageAdapter` protocol works —
S3, MinIO, Postgres, or anything else you want to back onto.

## License

MIT.
