"""Integration tests with a mocked LLM client.

We never hit the real Anthropic API in tests. Instead, we build a FakeClient
that implements the LLMClient protocol and returns canned structured/text
responses. This proves the wiring through api.py is correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Type

import pytest
from pydantic import BaseModel

from ringwood import Wiki
from ringwood.engine.decision import _DecisionOut, Operation
from ringwood.engine.classifier import Classification
from ringwood.llm import LLMUsage, StructuredResponse, TextResponse


@pytest.fixture(autouse=True)
def _no_ambient_api_key(monkeypatch):
    """These tests inject a FakeClient directly; never let a real key leak in."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# ── Fake client ───────────────────────────────────────────────────────────


@dataclass
class FakeClient:
    """Hand-rolled test double. Returns pre-programmed responses by schema."""

    responses: dict[str, BaseModel]
    texts: dict[str, str]
    calls: list[dict] = None

    def __post_init__(self) -> None:
        self.calls = []

    available = True

    def text_call(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 1024,
        cache_system: bool = False,
    ) -> TextResponse:
        self.calls.append(
            {"kind": "text", "model": model, "user": user[:80], "cache": cache_system}
        )
        # Route on any substring of the system prompt. Tests register prefixes.
        for key, text in self.texts.items():
            if key in system:
                return TextResponse(text=text, usage=LLMUsage(input_tokens=10, output_tokens=5))
        return TextResponse(text="default text", usage=LLMUsage(input_tokens=10, output_tokens=5))

    def structured_call(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: Type[BaseModel],
        max_tokens: int = 1024,
        cache_system: bool = False,
    ) -> StructuredResponse[Any]:
        self.calls.append({"kind": "structured", "model": model, "schema": schema.__name__})
        parsed = self.responses.get(schema.__name__)
        return StructuredResponse(
            parsed=parsed,
            raw_text=parsed.model_dump_json() if parsed else "",
            usage=LLMUsage(input_tokens=50, output_tokens=20),
        )


# ── Tests ─────────────────────────────────────────────────────────────────


def test_classifier_uses_llm_when_available(tmp_path: Path):
    fake = FakeClient(
        responses={
            "Classification": Classification(
                save=True, page_type="synthesis",
                title_slug="llm-verdict", rationale="LLM said save",
            ),
            # Decision is ADD because no candidates on a fresh wiki
            "_DecisionOut": _DecisionOut(
                operation="ADD", target_page_id=None,
                rationale="new to the wiki", confidence=0.8,
            ),
        },
        texts={"You write one-line retrieval": "Wiki context prefix test."},
    )
    wiki = Wiki(root=tmp_path, llm=fake)
    result = wiki.record_answer(
        question="What's 2+2?",   # would be rejected by rule-based, but LLM says save
        answer="4",
    )
    assert result is not None
    assert result.operation == Operation.ADD
    # confirm the classifier and decision schemas were both called
    schemas = {c.get("schema") for c in fake.calls if c["kind"] == "structured"}
    assert "Classification" in schemas
    assert "_DecisionOut" in schemas


def test_decision_update_routes_through_rewriter(tmp_path: Path):
    fake = FakeClient(
        responses={
            "Classification": Classification(
                save=True, page_type="synthesis", title_slug="seed", rationale="ok"
            ),
            "_DecisionOut": _DecisionOut(
                operation="ADD", target_page_id=None,
                rationale="first entry", confidence=0.9,
            ),
        },
        texts={
            "You write one-line retrieval": "Seed page retrieval prefix.",
            "You rewrite wiki pages": "Seed rewritten body with NEW_INFO integrated.",
        },
    )
    wiki = Wiki(root=tmp_path, llm=fake)

    # First ingest → ADD
    r1 = wiki.ingest("Initial claim about X.", source_ref="s1", title="Seed")
    assert r1.operation == Operation.ADD
    seeded_id = r1.page_id

    # Re-program: second call returns UPDATE pointing at the seeded page.
    fake.responses["_DecisionOut"] = _DecisionOut(
        operation="UPDATE",
        target_page_id=seeded_id,
        rationale="extends seeded page",
        confidence=0.85,
    )
    # title overlaps the seed → FTS5 finds it as a candidate → LLM can UPDATE it
    r2 = wiki.ingest("Additional detail.", source_ref="s2", title="Seed")
    assert r2.operation == Operation.UPDATE
    assert r2.page_id == seeded_id

    page = wiki.get(seeded_id)
    assert "rewritten" in page.body.lower()
    assert "s2" in page.sources


def test_hallucinated_target_falls_back_to_add(tmp_path: Path):
    """LLM returns a page_id that doesn't exist → engine downgrades to ADD."""
    fake = FakeClient(
        responses={
            "_DecisionOut": _DecisionOut(
                operation="UPDATE",
                target_page_id="concept/does-not-exist",
                rationale="fake target",
                confidence=0.9,
            ),
        },
        texts={"You write one-line retrieval": "ctx"},
    )
    wiki = Wiki(root=tmp_path, llm=fake)
    result = wiki.ingest("Some new claim.", source_ref="s1", title="New")
    assert result.operation == Operation.ADD  # downgraded


def test_llm_parse_failure_falls_back_to_rules(tmp_path: Path):
    """If the LLM returns None (refusal), rule-based fallback kicks in."""
    fake = FakeClient(responses={}, texts={})  # parsed=None for everything
    wiki = Wiki(root=tmp_path, llm=fake)
    # record_answer with an explicit save phrase → rule-based says SAVE
    result = wiki.record_answer(
        question="remember this please",
        answer="The convention is snake_case.",
    )
    assert result is not None
    assert result.operation == Operation.ADD


def test_stub_client_keeps_everything_offline(tmp_path: Path):
    """No LLM at all → Phase 0 behaviour."""
    from ringwood.llm import StubClient
    wiki = Wiki(root=tmp_path, llm=StubClient())
    r = wiki.ingest("Test claim.", source_ref="s1", title="Claim")
    assert r.operation == Operation.ADD
    assert wiki.search("test")[0].page_id == r.page_id
