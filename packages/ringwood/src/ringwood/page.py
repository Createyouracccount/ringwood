"""Page model — markdown body + YAML frontmatter.

Design anchors (from PLAN.md §3):
  - Human-readable plain text (grep/git friendly).
  - Bitemporal metadata (Graphiti pattern): valid_at, invalid_at, last_confirmed.
  - Reinforcement counters feed retrieval priority; confidence decays with staleness.
  - `summary` field doubles as the Contextual Retrieval prefix that gets indexed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Iterable

import yaml


class PageKind(str, Enum):
    ENTITY = "entity"
    CONCEPT = "concept"
    DECISION = "decision"
    QUERY = "query"        # saved Q&A, Karpathy compounding
    SYNTHESIS = "synthesis"


class Volatility(str, Enum):
    VOLATILE = "volatile"  # 7d TTL — API prices, current versions
    PROJECT = "project"    # 90d TTL — in-flight decisions
    STABLE = "stable"      # no TTL — architecture, persona


Confidence = float  # 0.0 .. 1.0


_FRONTMATTER_DELIM = "---"


@dataclass
class Page:
    """A single wiki article.

    `body` is the markdown content *without* the YAML frontmatter block.
    Serialize with `to_markdown()`, parse with `Page.from_markdown()`.
    """

    id: str                                    # e.g. "concept/claude-prompt-caching"
    kind: PageKind
    title: str
    summary: str = ""                          # 50–100 token Contextual Retrieval prefix
    body: str = ""
    tags: list[str] = field(default_factory=list)

    # Bitemporal
    valid_at: date | None = None
    invalid_at: date | None = None             # set by engine, never user
    last_confirmed: date | None = None
    volatility: Volatility = Volatility.STABLE

    # Reinforcement
    confidence: Confidence = 0.5
    inbound_count: int = 0
    cite_count: int = 0
    reinforce_events: int = 0

    # Provenance
    sources: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    superseded_by: str | None = None

    # Book-keeping
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Serialization ────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        """Serialize to `---\\n<yaml>\\n---\\n<body>\\n`."""
        meta = self._frontmatter_dict()
        yaml_block = yaml.safe_dump(
            meta, sort_keys=False, allow_unicode=True, default_flow_style=False
        ).rstrip()
        return f"{_FRONTMATTER_DELIM}\n{yaml_block}\n{_FRONTMATTER_DELIM}\n{self.body.rstrip()}\n"

    @classmethod
    def from_markdown(cls, text: str) -> "Page":
        """Parse a file produced by `to_markdown()`. Raises ValueError on malformed input."""
        meta, body = _split_frontmatter(text)
        return cls._from_dict(meta, body)

    # ── Bitemporal helpers ───────────────────────────────────────────────

    def is_valid_at(self, when: date | None = None) -> bool:
        """True iff the page is considered active at the given date (default: today)."""
        when = when or date.today()
        if self.invalid_at is not None and self.invalid_at <= when:
            return False
        if self.valid_at is not None and self.valid_at > when:
            return False
        return True

    def invalidate(self, at: date | None = None, superseded_by: str | None = None) -> None:
        """Soft-delete. Engine translates DELETE decisions into this call."""
        self.invalid_at = at or date.today()
        if superseded_by:
            self.superseded_by = superseded_by
        self.updated_at = datetime.now(timezone.utc)

    def reinforce(self, agreement_score: float = 1.0) -> None:
        """NOOP-on-same-fact reinforcement. See PLAN.md §4-D."""
        import math
        self.cite_count += 1
        self.reinforce_events += 1
        self.confidence = min(
            0.99,
            0.5
            + 0.05 * math.log(1 + self.cite_count)
            + 0.1 * agreement_score,
        )
        self.last_confirmed = date.today()
        self.updated_at = datetime.now(timezone.utc)

    def touch_inbound(self) -> None:
        """Called when another page links to this one. Boosts retrieval priority."""
        self.inbound_count += 1
        self.updated_at = datetime.now(timezone.utc)

    # ── Internal ─────────────────────────────────────────────────────────

    def _frontmatter_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind.value,
            "title": self.title,
            "tags": self.tags,
            "summary": self.summary,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "last_confirmed": self.last_confirmed,
            "volatility": self.volatility.value,
            "confidence": round(self.confidence, 3),
            "inbound_count": self.inbound_count,
            "cite_count": self.cite_count,
            "reinforce_events": self.reinforce_events,
            "sources": self.sources,
            "related": self.related,
            "superseded_by": self.superseded_by,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "updated_at": self.updated_at.isoformat(timespec="seconds"),
        }
        return {k: v for k, v in d.items() if v not in (None, [], "")}

    @classmethod
    def _from_dict(cls, meta: dict[str, Any], body: str) -> "Page":
        return cls(
            id=meta["id"],
            kind=PageKind(meta["kind"]),
            title=meta["title"],
            summary=meta.get("summary", ""),
            body=body,
            tags=list(meta.get("tags", [])),
            valid_at=_as_date(meta.get("valid_at")),
            invalid_at=_as_date(meta.get("invalid_at")),
            last_confirmed=_as_date(meta.get("last_confirmed")),
            volatility=Volatility(meta.get("volatility", "stable")),
            confidence=float(meta.get("confidence", 0.5)),
            inbound_count=int(meta.get("inbound_count", 0)),
            cite_count=int(meta.get("cite_count", 0)),
            reinforce_events=int(meta.get("reinforce_events", 0)),
            sources=list(meta.get("sources", [])),
            related=list(meta.get("related", [])),
            superseded_by=meta.get("superseded_by"),
            created_at=_as_dt(meta.get("created_at")),
            updated_at=_as_dt(meta.get("updated_at")),
        )


# ── Module helpers ────────────────────────────────────────────────────────

def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (meta_dict, body). Raises ValueError if frontmatter block is missing."""
    if not text.startswith(_FRONTMATTER_DELIM):
        raise ValueError("page is missing the YAML frontmatter delimiter (`---`)")
    parts = text.split(_FRONTMATTER_DELIM, 2)
    # parts == ["", <yaml>, <body>]
    if len(parts) < 3:
        raise ValueError("page frontmatter block is not terminated")
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    if not isinstance(meta, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return meta, body


def _as_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        return date.fromisoformat(v)
    raise ValueError(f"cannot coerce {v!r} to date")


def _as_dt(v: Any) -> datetime:
    if v is None:
        return datetime.now(timezone.utc)
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    if isinstance(v, str):
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise ValueError(f"cannot coerce {v!r} to datetime")
