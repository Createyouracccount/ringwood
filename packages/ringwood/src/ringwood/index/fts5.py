"""SQLite FTS5 index — Phase 0 default.

Why FTS5?
  - Zero external deps. Every Python ≥3.10 ships SQLite with FTS5 compiled in.
  - BM25 ranking built-in.
  - Great for <100MB corpora (Anthropic's agentic search recipe works here).

The `summary` (Contextual Retrieval prefix) is concatenated into the indexed
text — Anthropic's "Contextual BM25" trick. Dropped retrieval failure from
5.7% to 2.9% in their benchmark.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from ..page import Page
from .base import IndexAdapter, SearchHit


_SCHEMA = """
-- Trigram tokenizer is non-negotiable for Korean / Japanese / Chinese:
-- unicode61 splits on whitespace, so '컨벤션은' never matches '컨벤션'
-- (a BM25 miss for the same word with a different 조사). Trigram works
-- on 3-char rolling windows, which is agnostic to morphology.
--
-- Requires SQLite ≥ 3.34; ships with every Python ≥ 3.10 on all platforms
-- we target. See https://sqlite.org/fts5.html#the_experimental_trigram_tokenizer
CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(
    page_id       UNINDEXED,
    title,
    summary,                -- Contextual Retrieval prefix
    tags,
    body,
    valid_flag    UNINDEXED, -- 1 if live, 0 if invalidated
    priority      UNINDEXED, -- z_score(inbound_count) for ranking boost
    tokenize = 'trigram'
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Fts5Index(IndexAdapter):
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        # Concurrency: the long-running MCP server holds one connection while
        # the Stop hook spawns a separate `ringwood-capture` process that also
        # writes. Default SQLite raises "database is locked" on the second
        # writer, so the hook's upsert fails silently — the page file lands on
        # disk but never reaches the FTS index, and later searches return no
        # hits. WAL lets readers and a writer coexist; busy_timeout lets the
        # second writer wait its turn instead of blowing up immediately.
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.executescript(_SCHEMA)

    # ── IndexAdapter ─────────────────────────────────────────────────────

    def upsert(self, page: Page) -> None:
        # FTS5 has no native UPSERT — delete then insert.
        self._conn.execute("DELETE FROM pages WHERE page_id = ?", (page.id,))
        self._conn.execute(
            """INSERT INTO pages
               (page_id, title, summary, tags, body, valid_flag, priority)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                page.id,
                page.title,
                page.summary,
                " ".join(page.tags),
                page.body,
                0 if page.invalid_at is not None else 1,
                float(page.inbound_count),  # priority surrogate in Phase 0
            ),
        )

    def delete(self, page_id: str) -> None:
        self._conn.execute("DELETE FROM pages WHERE page_id = ?", (page_id,))

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        if not query.strip():
            return []
        # Weight the contextual prefix (summary) higher than body; title highest.
        # FTS5 column weights: page_id, title, summary, tags, body, valid_flag, priority.
        # UNINDEXED columns must receive weight 0.
        sql = """
            SELECT page_id,
                   title,
                   summary,
                   snippet(pages, 4, '«', '»', ' … ', 16) AS snip,
                   -bm25(pages, 0.0, 8.0, 4.0, 2.0, 1.0, 0.0, 0.0) AS score
            FROM pages
            WHERE pages MATCH ?
              AND valid_flag = 1
            ORDER BY score DESC, priority DESC
            LIMIT ?
        """
        try:
            rows = self._conn.execute(sql, (_escape_fts(query), limit)).fetchall()
        except sqlite3.OperationalError:
            # malformed FTS query — retry with quoted phrase
            rows = self._conn.execute(sql, (f'"{query}"', limit)).fetchall()
        return [
            SearchHit(page_id=r[0], title=r[1], summary=r[2], score=float(r[4]), snippet=r[3])
            for r in rows
        ]

    def rebuild(self, pages: list[Page]) -> None:
        self._conn.execute("DELETE FROM pages")
        for p in pages:
            self.upsert(p)

    def close(self) -> None:
        self._conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────

import re as _re

# Characters that have special meaning to the FTS5 query parser. Any of these
# in a raw query means we must quote-tokenize or strip rather than pass through.
_FTS_SPECIAL = set('"*:()+-^{}[]')

# Characters that are "punctuation noise" and should be replaced with spaces
# before tokenization. Commas, colons, periods, semicolons and trailing
# 조사-attached punctuation break literal phrase matching ("보강:" ≠ "보강")
# and there is no reason to carry them into the search query.
_PUNCT_NOISE = _re.compile(r"[,.:;!?\"'`()\[\]{}<>\\/|~^]+")


def _escape_fts(query: str) -> str:
    """Make a user-typed query safe for FTS5 MATCH.

    Strategy: strip punctuation noise, split on whitespace, OR-combine the
    tokens so any matching term contributes to BM25. AND semantics made the
    search brittle to morphology (same word with different 조사 missed).
    A tiny minimum token length (2 chars) drops single particles that add
    noise.
    """
    if not query or not query.strip():
        return ""
    cleaned = _PUNCT_NOISE.sub(" ", query)
    words = [w for w in cleaned.split() if len(w) >= 2]
    if not words:
        # Fall back to the original string, quoted defensively.
        safe = query.replace('"', "")
        return f'"{safe}"'
    # Quote each token to keep FTS operators inside the word literal, then
    # OR them so any match boosts the score.
    return " OR ".join(f'"{w}"' for w in words)
