"""Lint / nightly sweep — keeps the wiki honest.

Checks (PLAN.md §4-F):
  - broken [[wikilinks]]
  - stale pages (no edit in 90d + inbound_count == 0)
  - orphan pages (no inbound references anywhere)
  - contradiction suspects (sampled, Sonnet-judged) — Phase 1+

Phase 0 implements the first three (pure string/graph checks, no LLM).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..page import Page, Volatility


_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class LintReport:
    broken_links: list[tuple[str, str]] = field(default_factory=list)   # (page_id, target)
    stale: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    invalidated: list[str] = field(default_factory=list)
    contradictions: list[tuple[str, str]] = field(default_factory=list)

    def summary_line(self) -> str:
        parts = []
        if self.broken_links:   parts.append(f"{len(self.broken_links)} broken links")
        if self.stale:          parts.append(f"{len(self.stale)} stale")
        if self.orphans:        parts.append(f"{len(self.orphans)} orphans")
        if self.invalidated:    parts.append(f"{len(self.invalidated)} invalidated")
        if self.contradictions: parts.append(f"{len(self.contradictions)} contradictions")
        return ", ".join(parts) if parts else "clean"


def run_lint(pages: list[Page]) -> LintReport:
    """Pure function — accepts a live snapshot, returns a report.

    `pages` must include invalidated ones (valid_flag=0) so the link checker
    can tell "target exists but is invalid" from "target missing".
    """
    report = LintReport()
    by_id = {p.id: p for p in pages}
    inbound: dict[str, int] = {p.id: 0 for p in pages}

    for p in pages:
        if p.invalid_at is not None:
            report.invalidated.append(p.id)
            continue  # skip link/stale checks on dead pages

        for m in _WIKILINK.finditer(p.body):
            target = _resolve_wikilink(m.group(1), by_id)
            if target is None:
                report.broken_links.append((p.id, m.group(1)))
            else:
                inbound[target] = inbound.get(target, 0) + 1

    today = date.today()
    for p in pages:
        if p.invalid_at is not None:
            continue
        # Staleness is a time-only signal: has this volatility bucket's
        # freshness window expired? The previous gate also required
        # cite_count == 0, which meant any page cited once — even years ago —
        # was considered fresh forever. That hid genuine drift.
        horizon = _freshness_horizon(p.volatility)
        cutoff = today - horizon if horizon else None
        last_edit = p.updated_at.date()
        if cutoff and last_edit < cutoff:
            report.stale.append(p.id)
        # Orphan is a graph-only signal: no page links to this one.
        # Intentionally independent of cite_count (which tracks external uses
        # via record_answer) and from staleness — a freshly written note
        # with no backlinks is still an orphan worth flagging.
        if inbound.get(p.id, 0) == 0:
            report.orphans.append(p.id)

    return report


def _resolve_wikilink(raw: str, by_id: dict[str, Page]) -> str | None:
    """Resolve `[[target]]` to a page id.

    Accept either:
      - full id ("concept/prompt-caching")
      - bare slug that matches exactly one page (e.g. "prompt-caching")
      - title exact match
    """
    raw = raw.strip()
    if raw in by_id:
        return raw
    # Title match
    title_hit = [pid for pid, p in by_id.items() if p.title.lower() == raw.lower()]
    if len(title_hit) == 1:
        return title_hit[0]
    # Slug match (last path component)
    slug_hit = [pid for pid in by_id if pid.rsplit("/", 1)[-1] == raw]
    if len(slug_hit) == 1:
        return slug_hit[0]
    return None


def _freshness_horizon(volatility: Volatility) -> timedelta | None:
    if volatility == Volatility.VOLATILE:
        return timedelta(days=7)
    if volatility == Volatility.PROJECT:
        return timedelta(days=90)
    return None  # stable: never auto-stale
