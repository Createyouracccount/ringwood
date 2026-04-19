"""Inline citation rendering.

Every MCP tool response that returns knowledge from the wiki should include
a short, consistent citation footer. This is the second half of the
"growth is visible" UX commitment in PLAN.md §7 — without it, users can't
tell that the wiki actually helped.

The rule: callers build a CitationSet from the SearchHits they used, and
we render it as a single `📚 Referenced: ...` line. Keep it terse: hash,
title, path. The LLM can decide whether to include it verbatim in its reply.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from .index.base import SearchHit
from .page import Page


@dataclass
class Citation:
    page_id: str
    title: str
    last_confirmed: date | None = None
    cite_count: int = 0

    def render_inline(self) -> str:
        age = _relative_days(self.last_confirmed) if self.last_confirmed else "new"
        return f"[{self.title}]({self.page_id}) · {age} · cited {self.cite_count}×"

    @classmethod
    def from_page(cls, page: Page) -> "Citation":
        return cls(
            page_id=page.id,
            title=page.title,
            last_confirmed=page.last_confirmed,
            cite_count=page.cite_count,
        )

    @classmethod
    def from_hit(cls, hit: SearchHit) -> "Citation":
        return cls(page_id=hit.page_id, title=hit.title)


def render_footer(citations: list[Citation]) -> str:
    """Return a single-line markdown footer, or '' when nothing to cite.

    Designed to be appended to a tool response or an assistant answer.
    Stable format lets downstream UIs parse it if they want to highlight it.
    """
    if not citations:
        return ""
    # Dedupe by page_id, preserve order.
    seen: set[str] = set()
    unique: list[Citation] = []
    for c in citations:
        if c.page_id in seen:
            continue
        seen.add(c.page_id)
        unique.append(c)

    rendered = " · ".join(c.render_inline() for c in unique[:5])
    more = f" (+{len(unique) - 5} more)" if len(unique) > 5 else ""
    return f"📚 Referenced: {rendered}{more}"


def _relative_days(when: date) -> str:
    """Tiny humanizer. 'today', '3d ago', '2mo ago', '1y ago'."""
    today = date.today()
    diff = (today - when).days
    if diff <= 0:
        return "today"
    if diff == 1:
        return "yesterday"
    if diff < 14:
        return f"{diff}d ago"
    if diff < 60:
        return f"{diff // 7}w ago"
    if diff < 365:
        return f"{diff // 30}mo ago"
    return f"{diff // 365}y ago"
