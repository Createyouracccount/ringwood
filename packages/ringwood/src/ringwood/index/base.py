"""Search index contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..page import Page


@dataclass
class SearchHit:
    """Single search result. Engine and MCP surface use this verbatim."""

    page_id: str
    title: str
    summary: str
    score: float
    snippet: str = ""


@runtime_checkable
class IndexAdapter(Protocol):
    def upsert(self, page: Page) -> None:
        """Index or re-index a page. Called on every wiki.ingest/UPDATE."""
        ...

    def delete(self, page_id: str) -> None:
        """Remove a page from the index. Called on hard deletes (rare).
        Soft deletes (invalid_at) are handled by filtering at search time."""
        ...

    def search(
        self, query: str, limit: int = 10, *, kind: str | None = None
    ) -> list[SearchHit]:
        """Full-text search. Invalid pages MUST be excluded by the adapter.

        When `kind` is provided, results are restricted to pages of that
        PageKind value (e.g. "decision", "query"). Adapters that cannot
        filter natively should filter post-hoc on the result set.
        """
        ...

    def rebuild(self, pages: list[Page]) -> None:
        """Drop and recreate the index from a list of live pages. For lint GC."""
        ...

    def close(self) -> None:
        ...
