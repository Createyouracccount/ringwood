"""Search index adapters.

Phase 0: SQLite FTS5 (BM25). Zero external dependencies, <100MB corpus sweet spot.
Phase 5: LanceDB vector + reranker for larger corpora.
"""

from .base import IndexAdapter, SearchHit
from .fts5 import Fts5Index

__all__ = ["IndexAdapter", "SearchHit", "Fts5Index"]
