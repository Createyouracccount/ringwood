"""Live compounding tests — requires ANTHROPIC_API_KEY.

Drives the real Anthropic API to verify that Phase 1's engine actually picks
the right ADD/UPDATE/DELETE/NOOP action on realistic scenarios. These are
the tests that justify the project's value claim: "answers compound".

Data lives in tests_live/golden/knowledge_updates.yaml (Korean, LongMemEval-
style). Each case walks a fresh wiki through setup → new_event → assertions.

Cost: ~$0.05 per run (10 cases × ~5 LLM calls × Haiku/Sonnet mix).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from ringwood import Wiki
from ringwood.engine.decision import Operation

from .conftest import skip_without_key


GOLDEN_PATH = Path(__file__).parent / "golden" / "knowledge_updates.yaml"


# ── dataclass for readability ─────────────────────────────────────────────


@dataclass
class GoldenCase:
    id: str
    category: str
    setup_events: list[dict]
    new_event: dict | None
    expected_action: str | None
    expected_action_any: list[str] | None
    query: str | None
    must_contain_any: list[str]
    must_not_contain: list[str]
    expected_retrieval_empty: bool
    rationale: str

    @classmethod
    def from_yaml(cls, raw: dict[str, Any]) -> "GoldenCase":
        return cls(
            id=raw["id"],
            category=raw["category"],
            setup_events=raw.get("setup_events") or [],
            new_event=raw.get("new_event"),
            expected_action=raw.get("expected_action"),
            expected_action_any=raw.get("expected_action_any"),
            query=raw.get("query"),
            must_contain_any=raw.get("must_contain_any") or [],
            must_not_contain=raw.get("must_not_contain") or [],
            expected_retrieval_empty=raw.get("expected_retrieval_empty", False),
            rationale=raw.get("rationale", ""),
        )


def _load_cases() -> list[GoldenCase]:
    if not GOLDEN_PATH.exists():
        return []
    data = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    return [GoldenCase.from_yaml(c) for c in data.get("cases", [])]


CASES = _load_cases()


# ── the parameterized test ────────────────────────────────────────────────


@skip_without_key
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES] or None)
def test_golden_scenario(live_wiki: Wiki, case: GoldenCase):
    if not CASES:
        pytest.skip("no golden cases found")

    # ── Phase 1: seed the wiki ─────────────────────────────────────────
    for i, ev in enumerate(case.setup_events):
        result = live_wiki.ingest(
            text=ev["text"],
            source_ref=ev.get("source", f"setup-{i}"),
        )
        assert result.page_id, f"{case.id}: setup event {i} failed to persist"

    # ── Phase 2: apply the new event (if any) ──────────────────────────
    if case.new_event is not None:
        result = live_wiki.ingest(
            text=case.new_event["text"],
            source_ref=case.new_event.get("source", "new"),
        )
        expected = _expected_actions(case)
        got = result.operation.value
        assert got in expected, (
            f"{case.id}: expected action in {expected}, got {got}\n"
            f"  rationale: {case.rationale}\n"
            f"  engine rationale: {result.rationale!r}"
        )

    # ── Phase 3: query assertions ──────────────────────────────────────
    if case.query:
        hits = live_wiki.search(case.query, limit=5)

        if case.expected_retrieval_empty:
            assert not hits, (
                f"{case.id}: abstention case expected 0 hits, got {len(hits)}: "
                f"{[h.page_id for h in hits]}"
            )

        if case.must_contain_any:
            # Look inside the full page bodies, not just summaries.
            hit_bodies = _collect_hit_bodies(live_wiki, hits)
            assert any(
                phrase in hit_bodies for phrase in case.must_contain_any
            ), (
                f"{case.id}: query '{case.query}' missed required phrase\n"
                f"  wanted any of: {case.must_contain_any}\n"
                f"  top hit bodies: {hit_bodies[:300]}"
            )

        if case.must_not_contain:
            # Live pages only (invalidated should not show up in search).
            live_bodies = _collect_hit_bodies(live_wiki, hits)
            for forbidden in case.must_not_contain:
                assert forbidden not in live_bodies, (
                    f"{case.id}: forbidden phrase '{forbidden}' leaked into "
                    f"active search results (stale retention bug)"
                )


# ── helpers ───────────────────────────────────────────────────────────────


def _expected_actions(case: GoldenCase) -> set[str]:
    if case.expected_action:
        return {case.expected_action}
    if case.expected_action_any:
        return set(case.expected_action_any)
    return {"ADD", "UPDATE", "DELETE", "NOOP"}


def _collect_hit_bodies(wiki: Wiki, hits) -> str:
    parts: list[str] = []
    for h in hits:
        try:
            page = wiki.get(h.page_id)
            parts.append(page.body)
            parts.append(page.summary)
        except Exception:
            parts.append(h.snippet)
    return "\n".join(parts)
