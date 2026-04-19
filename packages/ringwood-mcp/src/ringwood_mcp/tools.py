"""Tool registrations.

Design notes:
  - Each tool docstring is the description surfaced to the LLM. Keep them
    action-oriented — the LLM will pick tools based on this.
  - Return types are plain dict / list[dict] so the MCP layer auto-generates
    JSON schema from type hints.
  - Errors raise ValueError/LookupError; FastMCP forwards them as tool errors
    with human-readable messages.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ringwood import Wiki, PageKind, Volatility
from ringwood.citation import Citation, render_footer
from ringwood.storage.base import PageNotFound


def register_tools(mcp: FastMCP, wiki: Wiki) -> None:

    @mcp.tool()
    async def search_wiki(query: str, limit: int = 10) -> dict:
        """Search the wiki for pages relevant to `query`.

        Invalidated (superseded) pages are excluded automatically. Call this
        BEFORE answering domain questions so you can ground the response in
        the user's own prior knowledge.

        Returns {"hits": [...], "citation_footer": "📚 Referenced: ..."}.
        When you cite the wiki in your reply, append the citation_footer
        verbatim so the user sees what they actually got from their wiki.
        """
        hits = wiki.search(query, limit=limit)
        # Pull full pages for citation metadata (cite_count, last_confirmed)
        citations: list[Citation] = []
        for h in hits:
            try:
                page = wiki.get(h.page_id)
                citations.append(Citation.from_page(page))
            except PageNotFound:
                citations.append(Citation.from_hit(h))
        # BM25 produces very small values when the corpus is tiny (IDF ≈ 0),
        # so raw scores round to 0.000 and look broken. Expose rank instead —
        # what matters for ranking is the order, and rank is language-agnostic.
        return {
            "hits": [
                {
                    "page_id": h.page_id,
                    "title": h.title,
                    "summary": h.summary,
                    "snippet": h.snippet,
                    "rank": i + 1,
                    "score": round(h.score, 6),
                }
                for i, h in enumerate(hits)
            ],
            "citation_footer": render_footer(citations),
        }

    @mcp.tool()
    async def get_article(page_id: str) -> dict:
        """Read the full markdown of a wiki page.

        Use the `page_id` returned by `search_wiki` (e.g. `concept/caching`).
        Raises LookupError if the page does not exist.
        """
        try:
            page = wiki.get(page_id)
        except PageNotFound:
            raise LookupError(f"page not found: {page_id!r}")
        return {
            "page_id": page.id,
            "title": page.title,
            "kind": page.kind.value,
            "tags": page.tags,
            "summary": page.summary,
            "body": page.body,
            "valid_at": page.valid_at.isoformat() if page.valid_at else None,
            "invalid_at": page.invalid_at.isoformat() if page.invalid_at else None,
            "last_confirmed": page.last_confirmed.isoformat() if page.last_confirmed else None,
            "confidence": page.confidence,
            "inbound_count": page.inbound_count,
            "cite_count": page.cite_count,
            "sources": page.sources,
        }

    @mcp.tool()
    async def ingest_source(
        text: str,
        source_ref: str,
        title: str | None = None,
        kind: str = "synthesis",
        tags: list[str] | None = None,
        volatility: str = "stable",
    ) -> dict:
        """Add new knowledge to the wiki. The engine decides ADD/UPDATE/NOOP.

        `source_ref` should be a URL, file path, or short identifier for
        provenance. `kind` is one of: entity, concept, decision, query, synthesis.
        `volatility` is one of: volatile (7d TTL), project (90d), stable (∞).

        Use this when the user provides durable information (a decision,
        a convention, a discovered fact) — not for chat small-talk.
        """
        try:
            page_kind = PageKind(kind)
        except ValueError:
            raise ValueError(
                f"invalid kind {kind!r}; expected one of: entity, concept, decision, query, synthesis"
            )
        try:
            vol = Volatility(volatility)
        except ValueError:
            raise ValueError(
                f"invalid volatility {volatility!r}; expected: volatile, project, stable"
            )

        result = wiki.ingest(
            text=text,
            source_ref=source_ref,
            title=title,
            kind=page_kind,
            tags=tags or [],
            volatility=vol,
        )
        return {
            "operation": result.operation.value,
            "page_id": result.page_id,
            "rationale": result.rationale,
            "confidence": result.confidence,
        }

    @mcp.tool()
    async def record_answer(
        question: str,
        answer: str,
        sources: list[str] | None = None,
    ) -> dict:
        """File a Q&A into the wiki if the answer is worth remembering.

        Call this at the end of any conversation turn where the answer:
          - resolves a contradiction or corrects a prior belief,
          - synthesizes info from >=2 sources,
          - contains a named comparison/table, OR
          - the user asked to "remember", "save", or "pin" it.

        Returns {"saved": false, "reason": "..."} when the answer does not
        meet the bar — this is expected and healthy.
        """
        result = wiki.record_answer(question=question, answer=answer, sources=sources or [])
        if result is None:
            return {"saved": False, "reason": "classifier rejected (not wiki-worthy)"}
        return {
            "saved": True,
            "operation": result.operation.value,
            "page_id": result.page_id,
            "rationale": result.rationale,
        }

    @mcp.tool()
    async def list_recent_changes(days: int = 7) -> dict:
        """Show what the wiki learned in the last `days` days.

        Use this when the user asks 'what have I worked on recently?' or to
        surface fresh context at session start.
        """
        stats = wiki.stats(period="week" if days <= 7 else "month")
        return {
            "period_days": days,
            "new_pages": stats.new_pages,
            "updated_pages": stats.updated_pages,
            "invalidated_pages": stats.invalidated_pages,
            "questions_answered": stats.questions,
            "top_cited": [{"page_id": pid, "cite_count": n} for pid, n in stats.top_cited],
        }

    @mcp.tool()
    async def lint_wiki() -> dict:
        """Check wiki integrity: broken wikilinks, stale pages, orphans.

        Safe to call anytime. Returns a structured report you can show the
        user so they see what the wiki is flagging.
        """
        report = wiki.lint()
        return {
            "broken_links": [
                {"page_id": pid, "missing_target": tgt} for pid, tgt in report.broken_links
            ],
            "stale": report.stale,
            "orphans": report.orphans,
            "invalidated": report.invalidated,
            "contradictions": [
                {"page_a": a, "page_b": b} for a, b in report.contradictions
            ],
            "summary": report.summary_line(),
        }
