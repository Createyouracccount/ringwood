"""Phase 0 smoke tests — verify the whole public API round-trips.

These run in offline-stub mode. If the test environment has
`ANTHROPIC_API_KEY` set we clear it at fixture scope so we exercise the
rule-based fallbacks, not the network. Integration tests with a fake LLM
live in test_llm_integration.py.

Run: cd packages/ringwood && python -m pytest
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ringwood import Wiki, Page, PageKind, Volatility
from ringwood.engine.decision import Operation


@pytest.fixture(autouse=True)
def _force_offline(monkeypatch):
    """Ensure every test in this file uses the stub client."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("WIKI_LLM_PROVIDER", "stub")


def test_page_roundtrip(tmp_path: Path):
    p = Page(
        id="concept/hello",
        kind=PageKind.CONCEPT,
        title="Hello",
        summary="A greeting concept.",
        body="Hello, world.\n\nLots more text here.",
        tags=["demo", "greeting"],
        valid_at=date(2026, 4, 1),
        last_confirmed=date(2026, 4, 19),
        volatility=Volatility.STABLE,
        confidence=0.8,
    )
    md = p.to_markdown()
    assert md.startswith("---\n")
    q = Page.from_markdown(md)
    assert q.id == p.id
    assert q.title == p.title
    assert q.tags == p.tags
    assert q.confidence == pytest.approx(0.8)
    assert "Hello, world" in q.body


def test_wiki_ingest_and_search(tmp_path: Path):
    wiki = Wiki(root=tmp_path)
    result = wiki.ingest(
        "Prompt caching stores reusable prefix tokens to cut cost by up to 90%.",
        source_ref="https://anthropic.com/news/prompt-caching",
        title="Prompt caching",
    )
    assert result.operation == Operation.ADD
    assert result.page_id.startswith("synthesis/prompt-caching")

    hits = wiki.search("prompt caching")
    assert len(hits) == 1
    assert "prompt" in hits[0].title.lower()


def test_record_answer_saves_when_correction_detected(tmp_path: Path):
    wiki = Wiki(root=tmp_path)
    result = wiki.record_answer(
        question="Should we use camelCase?",
        answer="Actually, we use snake_case for files and camelCase only for variables.",
    )
    assert result is not None
    assert result.operation == Operation.ADD
    page = wiki.get(result.page_id)
    assert "snake_case" in page.body


def test_record_answer_skips_trivial(tmp_path: Path):
    wiki = Wiki(root=tmp_path)
    result = wiki.record_answer(
        question="What is 2+2?",
        answer="4",
    )
    assert result is None


def test_invalidate_and_search_excludes(tmp_path: Path):
    wiki = Wiki(root=tmp_path)
    r1 = wiki.ingest("Foo is a bar.", source_ref="s1", title="Foo")
    page = wiki.get(r1.page_id)
    page.invalidate()
    wiki.storage.write(page.id, page.to_markdown())
    wiki.index.upsert(page)
    assert wiki.search("foo") == []


def test_lint_detects_broken_link(tmp_path: Path):
    wiki = Wiki(root=tmp_path)
    wiki.ingest("A references [[nowhere]].", source_ref="s1", title="A")
    report = wiki.lint()
    assert any(target == "nowhere" for _, target in report.broken_links)


def test_stats_counts_new_pages(tmp_path: Path):
    wiki = Wiki(root=tmp_path)
    for i in range(3):
        wiki.ingest(f"Fact number {i}.", source_ref=f"s{i}", title=f"Fact {i}")
    s = wiki.stats(period="week")
    assert s.new_pages == 3
    assert s.invalidated_pages == 0
