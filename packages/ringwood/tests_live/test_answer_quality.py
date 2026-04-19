"""A/B answer quality test.

The real value question: does having our wiki make Claude's answers better?
We compare two answer paths on the same query:

    A) bare Claude — no prior context
    B) Claude + wiki — prior history ingested, search_wiki pulled top-k into
       the system prompt before generation

An LLM-as-judge (Sonnet) grades each answer against a gold rubric. Expected
pattern:
    - Q1-Q4: B should outperform A (wiki contains the required facts)
    - Q5: both should abstain; B gets a bonus if it's more honest

Output is a printed table + JSON summary. This is the **actual value proof**
of the project.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel, Field

from ringwood import Wiki

from .conftest import skip_without_key


GOLDEN_PATH = Path(__file__).parent / "golden" / "answer_quality.yaml"


# ── data types ────────────────────────────────────────────────────────────


@dataclass
class Scenario:
    id: str
    description: str
    history: list[str]
    new_query: str
    gold_must_include: list[str]
    must_not_include: list[str]
    only_with_wiki: str | None
    expect_abstain: bool = False

    @classmethod
    def from_yaml(cls, raw: dict[str, Any]) -> "Scenario":
        return cls(
            id=raw["id"],
            description=raw.get("description", ""),
            history=raw.get("history") or [],
            new_query=raw["new_query"],
            gold_must_include=raw.get("gold_must_include") or [],
            must_not_include=raw.get("must_not_include") or [],
            only_with_wiki=raw.get("only_with_wiki"),
            expect_abstain=raw.get("expect_abstain", False),
        )


class JudgeScore(BaseModel):
    """Structured verdict from the LLM judge."""

    factual_correctness: int = Field(ge=0, le=2, description="0=wrong, 1=partial, 2=fully correct")
    cites_wiki_specifics: bool = Field(
        description="True if the answer references facts that could only come from the user's history"
    )
    forbidden_phrase_used: bool = Field(description="True if must_not_include phrase appears")
    abstained_correctly: bool = Field(description="True when the answer honestly said it doesn't know")
    rationale: str = Field(description="One short sentence explaining the verdict")


def _load() -> list[Scenario]:
    if not GOLDEN_PATH.exists():
        return []
    data = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    return [Scenario.from_yaml(s) for s in data.get("scenarios", [])]


SCENARIOS = _load()


# ── judge prompt ──────────────────────────────────────────────────────────


JUDGE_SYSTEM = """\
You evaluate answers from two AI systems on the same question.

Given a QUESTION, a GOLD_RUBRIC of required facts, a list of FORBIDDEN_PHRASES,
and an ANSWER, return a structured verdict.

factual_correctness (0-2):
  0 — answer contradicts gold or hallucinates
  1 — answer is vague, missing key required facts, or partially wrong
  2 — answer matches all GOLD_RUBRIC items

cites_wiki_specifics: true if the answer references facts that are specific to
the user's history (dates, internal conventions, named decisions). False if it
only gives generic knowledge any model could produce.

forbidden_phrase_used: true if any FORBIDDEN_PHRASES substring appears.

abstained_correctly: true when the scenario expected abstention AND the answer
honestly said "I don't know" or similar. False otherwise.

Output JSON matching the schema. Be strict.
"""


# ── test wiring ───────────────────────────────────────────────────────────


def _answer_bare(llm, query: str) -> str:
    """Path A: no wiki. Just ask Claude the question cold."""
    resp = llm.text_call(
        model="claude-sonnet-4-6",
        system=(
            "You are a helpful assistant. Answer in Korean, concisely. "
            "If you don't know because you have no access to the user's "
            "personal history, say so honestly."
        ),
        user=query,
        max_tokens=400,
    )
    return resp.text


def _answer_with_wiki(wiki: Wiki, query: str) -> tuple[str, list[str]]:
    """Path B: search the wiki, inject top hits into the prompt, then answer."""
    hits = wiki.search(query, limit=5)
    context_blocks: list[str] = []
    used_ids: list[str] = []
    for h in hits:
        try:
            page = wiki.get(h.page_id)
            context_blocks.append(
                f"<wiki_page id={h.page_id!r} confidence={page.confidence:.2f}>\n"
                f"{page.body.strip()}\n</wiki_page>"
            )
            used_ids.append(h.page_id)
        except Exception:
            continue

    system = (
        "You are the user's AI assistant. Use the user's own wiki "
        "(their personal history) to answer. Prefer the wiki's facts over "
        "generic knowledge when they conflict. Cite specific wiki facts. "
        "Answer in Korean. If the wiki does not cover the question, say so.\n\n"
        + "\n\n".join(context_blocks)
        if context_blocks
        else "You are the user's AI assistant. The user has no relevant wiki "
        "pages for this question — say so honestly instead of guessing."
    )
    resp = wiki.llm.text_call(
        model="claude-sonnet-4-6",
        system=system,
        user=query,
        max_tokens=400,
    )
    return resp.text, used_ids


def _judge(wiki: Wiki, scenario: Scenario, answer: str) -> JudgeScore:
    user = (
        f"QUESTION:\n{scenario.new_query}\n\n"
        f"GOLD_RUBRIC (must include these facts): "
        f"{scenario.gold_must_include or '(none — abstention scenario)'}\n"
        f"FORBIDDEN_PHRASES (must NOT appear): "
        f"{scenario.must_not_include or '(none)'}\n"
        f"EXPECTED_ABSTAIN: {scenario.expect_abstain}\n\n"
        f"ANSWER:\n{answer}\n"
    )
    resp = wiki.llm.structured_call(
        model="claude-sonnet-4-6",
        system=JUDGE_SYSTEM,
        user=user,
        schema=JudgeScore,
        max_tokens=512,
    )
    if resp.parsed is None:
        # fall back to zero score on parse failure
        return JudgeScore(
            factual_correctness=0,
            cites_wiki_specifics=False,
            forbidden_phrase_used=False,
            abstained_correctly=False,
            rationale="judge parse failure",
        )
    return resp.parsed


# ── the actual test ──────────────────────────────────────────────────────


@skip_without_key
def test_wiki_improves_answers(live_wiki: Wiki, capsys):
    """End-to-end quality A/B. Emits a printed per-scenario table."""
    if not SCENARIOS:
        pytest.skip("no scenarios")

    rows = []
    total_bare_correct = 0
    total_wiki_correct = 0

    for sc in SCENARIOS:
        # ── seed wiki with history ──
        fresh = Wiki(root=live_wiki.root / f"_s_{sc.id}", llm=live_wiki.llm)
        for h in sc.history:
            fresh.ingest(text=h, source_ref=f"seed/{sc.id}")

        # ── A: bare ──
        a_answer = _answer_bare(live_wiki.llm, sc.new_query)
        a_verdict = _judge(live_wiki, sc, a_answer)

        # ── B: with wiki ──
        b_answer, used_ids = _answer_with_wiki(fresh, sc.new_query)
        b_verdict = _judge(live_wiki, sc, b_answer)

        # Per-case pass: factual_correctness ≥ 1 AND no forbidden phrase AND
        # (if abstain-expected, only count abstain-correct).
        def correct(v: JudgeScore, abstain_expected: bool) -> bool:
            if v.forbidden_phrase_used:
                return False
            if abstain_expected:
                return v.abstained_correctly
            return v.factual_correctness >= 2

        a_ok = correct(a_verdict, sc.expect_abstain)
        b_ok = correct(b_verdict, sc.expect_abstain)
        total_bare_correct += int(a_ok)
        total_wiki_correct += int(b_ok)

        rows.append({
            "id": sc.id,
            "desc": sc.description,
            "bare_fc": a_verdict.factual_correctness,
            "wiki_fc": b_verdict.factual_correctness,
            "bare_forbid": a_verdict.forbidden_phrase_used,
            "wiki_forbid": b_verdict.forbidden_phrase_used,
            "wiki_used_ids": used_ids,
            "a_answer": a_answer,
            "b_answer": b_answer,
            "a_rationale": a_verdict.rationale,
            "b_rationale": b_verdict.rationale,
            "a_ok": a_ok,
            "b_ok": b_ok,
        })

    # ── report ──────────────────────────────────────────────────────────
    with capsys.disabled():
        print("\n═══════════ answer-quality A/B ═══════════")
        for r in rows:
            print(f"\n─── {r['id']}: {r['desc']}")
            print(f"     bare  fc={r['bare_fc']}  ok={r['a_ok']}"
                  f"  forbid={r['bare_forbid']}")
            print(f"       └ {r['a_rationale']}")
            print(f"     wiki  fc={r['wiki_fc']}  ok={r['b_ok']}"
                  f"  used={r['wiki_used_ids']}")
            print(f"       └ {r['b_rationale']}")
            print(f"       A: {r['a_answer'][:160].replace(chr(10),' ')}")
            print(f"       B: {r['b_answer'][:160].replace(chr(10),' ')}")
        n = len(rows)
        print(f"\n═══ totals: bare {total_bare_correct}/{n}  "
              f"wiki {total_wiki_correct}/{n} ═══")

        # Dump JSON for further analysis (regression tracking).
        json_path = Path(__file__).parent / "quality_run.json"
        json_path.write_text(
            json.dumps({"rows": rows,
                        "bare_score": total_bare_correct,
                        "wiki_score": total_wiki_correct,
                        "total": n},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n📝 written {json_path.relative_to(Path.cwd())}")

    # The key assertion of the whole project: wiki should STRICTLY outperform
    # bare. Absolute thresholds are easy to game — require wiki > bare and
    # wiki ≥ 3/5 to guard against the degenerate case where both score zero.
    assert total_wiki_correct > total_bare_correct, (
        f"wiki did not beat bare ({total_wiki_correct} vs {total_bare_correct}). "
        f"see tests_live/quality_run.json for details."
    )
    assert total_wiki_correct >= 3, (
        f"wiki correct count {total_wiki_correct}/5 — below acceptable floor"
    )
