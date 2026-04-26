"""Phase 2 regression — graph CLI backend, kind filter, recency boost.

These cover the visibility surface (wiki.graph, search kind filter) and the
ranking signals layered on top of FTS5 BM25 (recency_score, priority).
Stays in offline-stub mode like test_smoke.py so CI doesn't need a key.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ringwood import Wiki, PageKind
from ringwood.api import WikiGraph
from ringwood.index.fts5 import _compute_priority, _recency_score


@pytest.fixture(autouse=True)
def _force_offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("WIKI_LLM_PROVIDER", "stub")


# ── graph ────────────────────────────────────────────────────────────────────

def test_graph_resolves_wikilinks(tmp_path: Path):
    # Bypass the decision engine — write two pages directly so we test
    # the graph builder, not the engine's NOOP/UPDATE merging.
    wiki = _wiki_with_pages(
        tmp_path,
        [
            ("concept/caching", "Caching", "Caching is described elsewhere."),
            ("synthesis/prefix", "Prefix", "See [[Caching]] for prefix details."),
        ],
    )
    g = wiki.graph()
    assert isinstance(g, WikiGraph)
    assert ("synthesis/prefix", "concept/caching") in g.edges
    assert not any(pid.startswith("?") for pid in g.nodes)


def test_graph_marks_unresolved_targets(tmp_path: Path):
    wiki = _wiki_with_pages(
        tmp_path,
        [("concept/refers", "Refers", "Refers to [[nowhere]].")],
    )
    g = wiki.graph()
    assert any(dst.startswith("?") for _, dst in g.edges)


def test_graph_dot_and_json_outputs(tmp_path: Path):
    wiki = _wiki_with_pages(
        tmp_path,
        [
            ("concept/a", "A", "Alpha entry."),
            ("synthesis/b", "B", "Mentions [[A]]."),
        ],
    )
    g = wiki.graph()

    dot = g.to_dot()
    assert dot.startswith("digraph wiki {")
    assert "->" in dot

    payload = g.to_json_dict()
    assert {"nodes", "edges"} <= payload.keys()
    assert payload["edges"], "expected at least one edge"


# ── search kind filter ──────────────────────────────────────────────────────

def test_search_kind_filter_excludes_other_kinds(tmp_path: Path):
    wiki = _wiki_with_pages(
        tmp_path,
        [
            ("decision/refund", "Refund policy", "policy is no refunds."),
            ("concept/policy", "Policy concept", "policy in general means a rule."),
        ],
    )
    decisions = wiki.search("policy", kind=PageKind.DECISION)
    concepts = wiki.search("policy", kind=PageKind.CONCEPT)
    assert decisions and all(h.page_id.startswith("decision/") for h in decisions)
    assert concepts and all(h.page_id.startswith("concept/") for h in concepts)


def test_search_no_kind_returns_all(tmp_path: Path):
    wiki = _wiki_with_pages(
        tmp_path,
        [
            ("decision/refund", "Refund", "policy is no refunds."),
            ("concept/policy", "Policy", "policy in general means a rule."),
        ],
    )
    hits = wiki.search("policy")
    kinds = {h.page_id.split("/", 1)[0] for h in hits}
    assert {"decision", "concept"} <= kinds


# ── recency boost ───────────────────────────────────────────────────────────

def test_recency_score_today_is_one():
    page = _stub_page(last_confirmed=date.today())
    assert _recency_score(page, today=date.today()) == pytest.approx(1.0)


def test_recency_score_half_life_at_90_days():
    today = date(2026, 4, 27)
    page = _stub_page(last_confirmed=today - timedelta(days=90))
    assert _recency_score(page, today=today) == pytest.approx(0.5, rel=1e-3)


def test_recency_falls_back_to_created_at_when_unconfirmed():
    today = date(2026, 4, 27)
    page = _stub_page(
        last_confirmed=None,
        created_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    # Created today, never confirmed → still treated as fresh.
    assert _recency_score(page, today=today) == pytest.approx(1.0)


def test_priority_blends_inbound_confidence_recency():
    today = date.today()
    fresh = _stub_page(inbound_count=0, confidence=0.5, last_confirmed=today)
    stale = _stub_page(inbound_count=0, confidence=0.5,
                       last_confirmed=today - timedelta(days=365))
    assert _compute_priority(fresh) > _compute_priority(stale)


# ── helpers ─────────────────────────────────────────────────────────────────

def _stub_page(**overrides):
    from ringwood.page import Page, PageKind, Volatility
    defaults = dict(
        id="concept/x",
        kind=PageKind.CONCEPT,
        title="X",
        summary="",
        body="",
        volatility=Volatility.STABLE,
        confidence=0.5,
        inbound_count=0,
        cite_count=0,
    )
    defaults.update(overrides)
    return Page(**defaults)


def _wiki_with_pages(root: Path, pages: list[tuple[str, str, str]]) -> Wiki:
    """Seed a wiki by writing pages directly via storage+index, skipping the
    decision engine. Each tuple is (page_id, title, body); kind is derived
    from the id prefix (`concept/...` → CONCEPT, etc.)."""
    from ringwood.page import Page, Volatility
    wiki = Wiki(root=root)
    for pid, title, body in pages:
        kind_str = pid.split("/", 1)[0]
        page = Page(
            id=pid,
            kind=PageKind(kind_str),
            title=title,
            summary=title,
            body=body,
            volatility=Volatility.STABLE,
        )
        wiki.storage.write(pid, page.to_markdown())
        wiki.index.upsert(page)
    return wiki
