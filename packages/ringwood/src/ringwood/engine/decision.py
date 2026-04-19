"""ADD / UPDATE / DELETE / NOOP decision (mem0 pattern).

Phase 1: Sonnet-backed. Falls back to a conservative rule when no API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from ..index.base import SearchHit
from ..llm import DEFAULT_SONNET, LLMClient


class Operation(str, Enum):
    ADD = "ADD"
    UPDATE = "UPDATE"
    DELETE = "DELETE"        # engine translates to invalid_at, not hard delete
    NOOP = "NOOP"


@dataclass
class Decision:
    operation: Operation
    target_page_id: str | None
    rationale: str
    confidence: float        # 0.0 .. 1.0


class _DecisionOut(BaseModel):
    """Structured return from the LLM. Validated before use."""

    operation: Literal["ADD", "UPDATE", "DELETE", "NOOP"]
    target_page_id: str | None = Field(
        default=None,
        description="page_id for UPDATE/DELETE/NOOP, null for ADD",
    )
    rationale: str = Field(description="One short sentence.")
    confidence: float = Field(ge=0.0, le=1.0)


DECISION_SYSTEM = """\
You maintain a persistent, append-only wiki. Given NEW_INFO and up to 20
CANDIDATE_PAGES from hybrid search, choose one operation.

Rules:
  ADD    — NEW_INFO introduces a net-new entity/concept not covered by any
           candidate.
  UPDATE — NEW_INFO refines or extends an existing candidate (same entity,
           richer text).
  DELETE — NEW_INFO contradicts a candidate AND is more recent/authoritative.
           You are NOT hard-deleting — the engine translates DELETE into an
           invalid_at stamp and preserves history.
  NOOP   — NEW_INFO is semantically equivalent to an existing page (a
           paraphrase, a restatement, a confirmation).

Be conservative: prefer NOOP over UPDATE when the new information adds no
new claim. Prefer UPDATE over DELETE unless the candidate is clearly wrong.

For UPDATE/DELETE/NOOP, `target_page_id` MUST match one of the candidate ids
exactly. For ADD, set `target_page_id` to null.
"""


def decide(
    new_info: str,
    candidates: list[SearchHit],
    *,
    llm: LLMClient | None = None,
    model: str = DEFAULT_SONNET,
) -> Decision:
    """Pick ADD/UPDATE/DELETE/NOOP. LLM-backed when available, rule-based otherwise."""
    if llm is not None and llm.available:
        result = _llm_decide(new_info, candidates, llm=llm, model=model)
        if result is not None:
            return result
    return _rule_based(new_info, candidates)


# ── LLM path ──────────────────────────────────────────────────────────────


def _llm_decide(
    new_info: str,
    candidates: list[SearchHit],
    *,
    llm: LLMClient,
    model: str,
) -> Decision | None:
    user = (
        f"NEW_INFO:\n{new_info.strip()}\n\n"
        f"CANDIDATE_PAGES:\n{format_candidates_for_prompt(candidates)}"
    )
    resp = llm.structured_call(
        model=model,
        system=DECISION_SYSTEM,
        user=user,
        schema=_DecisionOut,
        max_tokens=512,
    )
    out = resp.parsed
    if out is None:
        return None

    # Defend against the LLM hallucinating a page_id that is not in candidates.
    known_ids = {c.page_id for c in candidates}
    op = Operation(out.operation)
    target = out.target_page_id if out.target_page_id in known_ids else None
    if op in (Operation.UPDATE, Operation.DELETE, Operation.NOOP) and target is None:
        # No valid target → downgrade to ADD so we don't lose the information.
        op = Operation.ADD

    return Decision(
        operation=op,
        target_page_id=target,
        rationale=out.rationale,
        confidence=out.confidence,
    )


# ── Rule-based fallback ───────────────────────────────────────────────────


def _rule_based(new_info: str, candidates: list[SearchHit]) -> Decision:
    if not candidates:
        return Decision(
            operation=Operation.ADD,
            target_page_id=None,
            rationale="no similar pages found",
            confidence=0.6,
        )
    top = candidates[0]
    if top.title and top.title.lower() in new_info.lower():
        return Decision(
            operation=Operation.UPDATE,
            target_page_id=top.page_id,
            rationale=f"new info mentions existing page title '{top.title}'",
            confidence=0.55,
        )
    return Decision(
        operation=Operation.ADD,
        target_page_id=None,
        rationale="no strong match in top candidates",
        confidence=0.5,
    )


def format_candidates_for_prompt(candidates: list[SearchHit]) -> str:
    """Render candidates as the CANDIDATE_PAGES block for the decision prompt."""
    if not candidates:
        return "(none)"
    lines = []
    for c in candidates:
        summary = c.summary[:200].replace("\n", " ")
        lines.append(
            f'<page id="{c.page_id}" score="{c.score:.2f}">\n'
            f"{c.title} :: {summary}\n"
            f"</page>"
        )
    return "\n".join(lines)
