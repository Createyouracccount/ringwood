"""ringwood — compounding knowledge wiki, protocol-agnostic.

Public API:
    Wiki            — main entry point, composes storage + index + engine
    Page            — markdown + frontmatter model (bitemporal, confidence)
    IngestResult    — return type of Wiki.ingest / Wiki.record_answer
    SearchHit       — return type of Wiki.search
    LintReport      — return type of Wiki.lint
    Stats           — return type of Wiki.stats

Storage adapters live in ringwood.storage, index adapters in ringwood.index.
The Anthropic-powered engine (classifier / decision / rewrite) lives in
ringwood.engine — it is stubbed in Phase 0 and filled in Phase 1.
"""

from .api import Wiki, IngestResult, SearchHit, LintReport, Stats
from .env import load_env
from .page import Page, PageKind, Confidence, Volatility

__all__ = [
    "Wiki",
    "IngestResult",
    "SearchHit",
    "LintReport",
    "Stats",
    "Page",
    "PageKind",
    "Confidence",
    "Volatility",
    "load_env",
]

__version__ = "0.1.0"
