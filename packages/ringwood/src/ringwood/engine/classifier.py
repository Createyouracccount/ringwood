"""Answer-worthiness classifier.

Phase 1: Haiku-backed. When no API key is available we fall back to a
conservative regex so offline users still get sensible behavior.

PLAN.md §4-A write triggers in priority order:
  1. user correction ("no, actually ...") — strongest signal
  2. explicit save ("remember", "pin this")
  3. convention / decision detection
  4. recurring theme (threshold-gated, Phase 2)
  5. synthesized answer (>=2 sources or comparison/contradiction)
  6. code ingest (DeepWiki-style, 1 page per cluster, Phase 5)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from ..llm import DEFAULT_HAIKU, LLMClient, StubClient


PageType = Literal["synthesis", "comparison", "decision", "fact", "none"]


@dataclass
class ClassifyResult:
    save: bool
    page_type: str
    title_slug: str
    rationale: str


class Classification(BaseModel):
    """Emit this object exactly. No prose outside the schema."""

    save: bool = Field(description="True only if the answer is worth filing as a wiki page.")
    page_type: PageType = Field(
        description=(
            "synthesis: combines ≥2 sources. "
            "comparison: names a table or side-by-side. "
            "decision: records a convention, choice, or correction. "
            "fact: single lookupable claim. "
            "none: not worth saving."
        )
    )
    title_slug: str = Field(
        default="",
        description="kebab-case-slug under 60 chars. Empty when save=false.",
    )
    rationale: str = Field(description="One short sentence explaining the verdict.")


CLASSIFIER_SYSTEM = """\
You decide whether a Q&A should be filed as a wiki page.

Save only if ANY of these are true:
  (1) the answer synthesizes information from ≥2 sources,
  (2) it names a comparison/table between concepts,
  (3) it resolves a contradiction or corrects a prior claim,
  (4) the user explicitly asked to save/pin/remember,
  (5) the answer records a team/personal convention or decision.

Discard trivial lookups that any competent model could regenerate.

Bias toward NOT saving. A lean wiki of high-signal pages beats a junk drawer.
Output exactly one Classification object — no surrounding text.
"""


def classify(
    question: str,
    answer: str,
    *,
    llm: LLMClient | None = None,
    model: str = DEFAULT_HAIKU,
) -> ClassifyResult:
    """Return a ClassifyResult. Uses Haiku when available, regex otherwise."""
    if llm is not None and llm.available:
        result = _llm_classify(question, answer, llm=llm, model=model)
        if result is not None:
            return result
        # parse failure → rule-based fallback keeps the caller moving
    return _rule_based(question, answer)


def _llm_classify(
    question: str,
    answer: str,
    *,
    llm: LLMClient,
    model: str,
) -> ClassifyResult | None:
    user = f"QUESTION:\n{question.strip()}\n\nANSWER:\n{answer.strip()}"
    resp = llm.structured_call(
        model=model,
        system=CLASSIFIER_SYSTEM,
        user=user,
        schema=Classification,
        max_tokens=512,
    )
    if resp.parsed is None:
        return None
    slug = resp.parsed.title_slug or _slugify(question or answer[:60])
    return ClassifyResult(
        save=resp.parsed.save,
        page_type=resp.parsed.page_type,
        title_slug=slug if resp.parsed.save else "",
        rationale=resp.parsed.rationale,
    )


# ── Rule-based fallback (Phase 0 behaviour) ───────────────────────────────

_EXPLICIT = re.compile(
    r"\b(remember|save|pin|wiki(?:-it)?|add to wiki|file this|keep this)\b",
    re.IGNORECASE,
)
_CORRECTION = re.compile(
    r"\b(actually|no[, ]|that'?s wrong|correction|instead[, ]|rather)\b",
    re.IGNORECASE,
)
_DECISION = re.compile(
    r"\b(we (?:decided|agreed|will use|chose)|convention is|let'?s use|"
    r"standard is|our (?:approach|convention|rule))\b",
    re.IGNORECASE,
)


def _rule_based(question: str, answer: str) -> ClassifyResult:
    text = f"{question}\n{answer}"
    if _EXPLICIT.search(question):
        return ClassifyResult(True, "fact", _slugify(question), "explicit user save request")
    if _CORRECTION.search(text):
        return ClassifyResult(
            True, "decision", _slugify(question or answer[:60]), "correction detected"
        )
    if _DECISION.search(text):
        return ClassifyResult(
            True, "decision", _slugify(question or answer[:60]), "convention/decision detected"
        )
    if len(answer) > 500 and answer.count("\n\n") >= 2:
        return ClassifyResult(
            True, "synthesis", _slugify(question), "long multi-paragraph synthesis"
        )
    return ClassifyResult(False, "none", "", "no save signal detected")


def _slugify(text: str, max_len: int = 60) -> str:
    s = text.strip().lower()
    s = re.sub(r"[^\w\s가-힣-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s[:max_len].strip("-") or "untitled"
