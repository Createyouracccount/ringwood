"""Wiki — the public API.

Composes storage + index + engine. Callers (MCP server, custom adapters, tests)
use this and nothing else from ringwood internals.

Phase 0 scope:
  ✓ search / get                         — ready to use
  ✓ ingest / record_answer               — rule-based engine stubs (no API key)
  ✓ lint                                 — pure checks
  ✓ stats                                — derived from log.md + page metadata

Phase 1 swaps the engine stubs for Anthropic API calls without changing this
surface. Callers need not know.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from .engine.classifier import classify, ClassifyResult
from .engine.contextualize import contextualize
from .engine.decision import decide, Operation, Decision, format_candidates_for_prompt
from .engine.lint import run_lint, LintReport
from .engine.rewriter import rewrite
from .env import load_env
from .index import Fts5Index, IndexAdapter, SearchHit
from .llm import LLMClient, get_client
from .page import Page, PageKind, Volatility
from .storage import LocalFSStorage, StorageAdapter, PageNotFound


# ── Return types ──────────────────────────────────────────────────────────


@dataclass
class IngestResult:
    operation: Operation
    page_id: str
    rationale: str
    confidence: float


@dataclass
class Stats:
    period: str                          # e.g. "week"
    questions: int = 0
    pages_cited_avg: float = 0.0
    new_pages: int = 0
    updated_pages: int = 0
    invalidated_pages: int = 0
    top_cited: list[tuple[str, int]] = field(default_factory=list)


# ── Wiki ──────────────────────────────────────────────────────────────────


class Wiki:
    """Composition root. Keep this class thin — logic lives in engine/ modules."""

    def __init__(
        self,
        root: str | Path,
        *,
        storage: StorageAdapter | None = None,
        index: IndexAdapter | None = None,
        llm: LLMClient | None = None,
        load_dotenv: bool = True,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        # Load .env BEFORE picking the LLM client so ANTHROPIC_API_KEY is
        # visible to get_client(). `setdefault` semantics in load_env mean
        # real env vars win — a production secret manager can still override.
        if load_dotenv:
            load_env(self.root)
        self.storage: StorageAdapter = storage or LocalFSStorage(self.root)
        self.index: IndexAdapter = index or Fts5Index(self.root / ".index" / "fts5.db")
        # When no llm is provided, get_client() picks Anthropic if an API key
        # is set, otherwise a deterministic stub. Engine modules always check
        # .available before making network calls.
        self.llm: LLMClient = llm if llm is not None else get_client()

    # ── Search / get ─────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        return self.index.search(query, limit=limit)

    def get(self, page_id: str) -> Page:
        text = self.storage.read(page_id)     # may raise PageNotFound
        return Page.from_markdown(text)

    def list_ids(self, prefix: str | None = None) -> list[str]:
        return list(self.storage.list_ids(prefix))

    # ── Write path (ingest, record_answer) ───────────────────────────────

    def ingest(
        self,
        text: str,
        *,
        source_ref: str,
        title: str | None = None,
        kind: PageKind = PageKind.SYNTHESIS,
        tags: list[str] | None = None,
        volatility: Volatility = Volatility.STABLE,
    ) -> IngestResult:
        """Route NEW_INFO through the Decision engine and persist the outcome."""
        # Retrieve candidates from multiple query angles — title alone is
        # too sparse for BM25 to find semantically adjacent pages. Each
        # angle contributes; dedupe by page_id. Without this the decision
        # engine systematically returns ADD because it sees no prior art,
        # even when a closely related page exists.
        candidates = self._gather_candidates(text=text, title=title)
        decision = decide(text, candidates, llm=self.llm)

        if decision.operation == Operation.NOOP:
            return self._reinforce_existing(decision, source_ref)

        if decision.operation == Operation.DELETE and decision.target_page_id:
            # Graphiti-style supersession: stamp the old page as invalid AND
            # write the new page. Without the second step, contradiction
            # input silently loses information (the classic "DELETE means
            # my facts disappeared" bug).
            return self._supersede(
                decision=decision,
                new_text=text,
                title=title or _derive_title(text),
                kind=kind,
                tags=tags or [],
                source_ref=source_ref,
                volatility=volatility,
            )

        if decision.operation == Operation.UPDATE and decision.target_page_id:
            return self._update(decision, text, source_ref)

        # Default: ADD
        return self._add(
            text=text,
            title=title or _derive_title(text),
            kind=kind,
            tags=tags or [],
            source_ref=source_ref,
            volatility=volatility,
            decision=decision,
        )

    def record_answer(
        self,
        question: str,
        answer: str,
        *,
        sources: list[str] | None = None,
    ) -> IngestResult | None:
        """Persist a Q&A as a wiki page if it passes the worthiness classifier.

        Returns None when the classifier rejects the answer (no save needed)."""
        verdict: ClassifyResult = classify(question, answer, llm=self.llm)
        if not verdict.save:
            self._log(f"skipped (answer not worth saving): {verdict.rationale}")
            return None

        body = _format_qa_body(question, answer, sources or [])
        title = question.strip().rstrip("?.!") or verdict.title_slug.replace("-", " ").title()
        return self.ingest(
            text=body,
            source_ref="chat-session",
            title=title,
            kind=PageKind.QUERY if verdict.page_type == "fact" else PageKind.SYNTHESIS,
            tags=["auto-recorded", verdict.page_type],
            volatility=Volatility.PROJECT,
        )

    # ── Lint / stats ─────────────────────────────────────────────────────

    def lint(self) -> LintReport:
        pages = [self.get(pid) for pid in self.list_ids()]
        report = run_lint(pages)
        self._log(f"lint | {report.summary_line()}")
        return report

    # ── Candidate retrieval (internal) ───────────────────────────────────

    def _gather_candidates(
        self, *, text: str, title: str | None, per_query: int = 10
    ) -> list[SearchHit]:
        """Union of hits from several query angles.

        Why not just `index.search(title)`? BM25 rewards token overlap —
        a title like "변수명 컨벤션" misses an existing page titled
        "백엔드 네이밍 컨벤션" even though they overlap semantically.
        Querying with body excerpts recovers most of that gap on Phase 0
        (no embeddings yet). Phase 5 swaps this for hybrid dense+BM25.
        """
        queries: list[str] = []
        if title:
            queries.append(title)
        # First sentence of the body — usually contains the entity name.
        first_line = text.strip().split("\n", 1)[0][:200]
        if first_line and first_line != title:
            queries.append(first_line)
        # Longer excerpt for broader term overlap.
        body_excerpt = text.strip()[:400]
        if body_excerpt and body_excerpt not in queries:
            queries.append(body_excerpt)

        seen: dict[str, SearchHit] = {}
        for q in queries:
            for hit in self.index.search(q, limit=per_query):
                # Keep the hit with the highest score across queries.
                prior = seen.get(hit.page_id)
                if prior is None or hit.score > prior.score:
                    seen[hit.page_id] = hit

        return sorted(seen.values(), key=lambda h: h.score, reverse=True)[:20]

    def stats(self, period: Literal["day", "week", "month"] = "week") -> Stats:
        pages = [self.get(pid) for pid in self.list_ids()]
        since = _period_start(period)

        new_pages = sum(1 for p in pages if p.created_at.date() >= since)
        updated = sum(
            1
            for p in pages
            if p.created_at.date() < since and p.updated_at.date() >= since
        )
        invalidated = sum(
            1 for p in pages if p.invalid_at is not None and p.invalid_at >= since
        )
        top = sorted(pages, key=lambda p: p.cite_count, reverse=True)[:5]
        pages_cited_avg = (
            sum(p.cite_count for p in pages) / max(len(pages), 1) if pages else 0.0
        )

        # "questions answered" proxy: count QUERY-kind pages created in period.
        questions = sum(
            1
            for p in pages
            if p.kind == PageKind.QUERY and p.created_at.date() >= since
        )

        return Stats(
            period=period,
            questions=questions,
            pages_cited_avg=round(pages_cited_avg, 2),
            new_pages=new_pages,
            updated_pages=updated,
            invalidated_pages=invalidated,
            top_cited=[(p.id, p.cite_count) for p in top],
        )

    # ── Internals ────────────────────────────────────────────────────────

    def _add(
        self,
        *,
        text: str,
        title: str,
        kind: PageKind,
        tags: list[str],
        source_ref: str,
        volatility: Volatility,
        decision: Decision,
    ) -> IngestResult:
        slug = _slugify(title)
        page_id = f"{kind.value}/{slug}"
        # Avoid collisions on repeated ADDs of similarly-titled content.
        page_id = self._uniquify(page_id)

        page = Page(
            id=page_id,
            kind=kind,
            title=title,
            body=text,
            tags=tags,
            valid_at=date.today(),
            last_confirmed=date.today(),
            volatility=volatility,
            confidence=decision.confidence,
            sources=[source_ref] if source_ref else [],
        )
        page.summary = contextualize(page.title, page.body, llm=self.llm)
        self.storage.write(page.id, page.to_markdown())
        self.index.upsert(page)
        self._log(f"ADD {page.id} | {decision.rationale}")
        return IngestResult(
            operation=Operation.ADD,
            page_id=page.id,
            rationale=decision.rationale,
            confidence=decision.confidence,
        )

    def _update(
        self,
        decision: Decision,
        new_info: str,
        source_ref: str,
    ) -> IngestResult:
        assert decision.target_page_id is not None
        page = self.get(decision.target_page_id)
        page = rewrite(page, new_info, source_ref, llm=self.llm)
        page.summary = contextualize(page.title, page.body, llm=self.llm)
        page.updated_at = datetime.now(timezone.utc)
        page.last_confirmed = date.today()
        self.storage.write(page.id, page.to_markdown())
        self.index.upsert(page)
        self._log(f"UPDATE {page.id} | {decision.rationale}")
        return IngestResult(
            operation=Operation.UPDATE,
            page_id=page.id,
            rationale=decision.rationale,
            confidence=decision.confidence,
        )

    def _supersede(
        self,
        *,
        decision: Decision,
        new_text: str,
        title: str,
        kind: PageKind,
        tags: list[str],
        source_ref: str,
        volatility: Volatility,
    ) -> IngestResult:
        """Invalidate the old page AND write the new one, linked via
        `superseded_by`. This is the only correct translation of a DELETE
        decision: information is never dropped, but the live view reflects
        the new state.
        """
        assert decision.target_page_id is not None
        # 1) write the new page first so we have its id for the back-link.
        new_result = self._add(
            text=new_text,
            title=title,
            kind=kind,
            tags=tags,
            source_ref=source_ref,
            volatility=volatility,
            decision=decision,
        )
        # 2) stamp the old page as invalidated, pointing at the new one.
        old = self.get(decision.target_page_id)
        old.invalidate(superseded_by=new_result.page_id)
        self.storage.write(old.id, old.to_markdown())
        self.index.upsert(old)  # valid_flag=0 hides from search
        self._log(
            f"SUPERSEDE {old.id} → {new_result.page_id} | {decision.rationale}"
        )
        return IngestResult(
            operation=Operation.DELETE,
            page_id=new_result.page_id,  # callers want the live page id
            rationale=decision.rationale,
            confidence=decision.confidence,
        )

    def _reinforce_existing(self, decision: Decision, source_ref: str) -> IngestResult:
        target = decision.target_page_id or ""
        if target and self.storage.exists(target):
            page = self.get(target)
            page.reinforce(agreement_score=1.0)
            if source_ref and source_ref not in page.sources:
                page.sources.append(source_ref)
            self.storage.write(page.id, page.to_markdown())
            self.index.upsert(page)
            self._log(f"NOOP (reinforced) {page.id}")
            return IngestResult(
                operation=Operation.NOOP,
                page_id=page.id,
                rationale=decision.rationale,
                confidence=decision.confidence,
            )
        self._log("NOOP (no target)")
        return IngestResult(
            operation=Operation.NOOP,
            page_id="",
            rationale=decision.rationale,
            confidence=decision.confidence,
        )

    def _uniquify(self, page_id: str) -> str:
        if not self.storage.exists(page_id):
            return page_id
        i = 2
        while self.storage.exists(f"{page_id}-{i}"):
            i += 1
        return f"{page_id}-{i}"

    def _log(self, message: str) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.storage.append_log(f"- [{ts}] {message}")


# ── Module helpers ────────────────────────────────────────────────────────


def _derive_title(text: str, max_len: int = 80) -> str:
    first = text.strip().splitlines()[0] if text.strip() else "untitled"
    first = first.lstrip("# ").strip()
    return first[:max_len] or "untitled"


def _slugify(text: str, max_len: int = 60) -> str:
    import re as _re
    s = text.strip().lower()
    s = _re.sub(r"[^\w\s가-힣-]", "", s)
    s = _re.sub(r"\s+", "-", s)
    return s[:max_len].strip("-") or "untitled"


def _period_start(period: str) -> date:
    today = date.today()
    if period == "day":
        return today
    if period == "week":
        return today - timedelta(days=7)
    if period == "month":
        return today - timedelta(days=30)
    return today - timedelta(days=7)


def _format_qa_body(question: str, answer: str, sources: list[str]) -> str:
    lines = ["## Question", question.strip(), "", "## Answer", answer.strip()]
    if sources:
        lines.append("")
        lines.append("## Sources")
        lines.extend(f"- {s}" for s in sources)
    return "\n".join(lines) + "\n"


__all__ = ["Wiki", "IngestResult", "SearchHit", "LintReport", "Stats"]
