"""Page rewriter — integrates NEW_INFO into an existing page on UPDATE.

Phase 1: Sonnet rewrites the body holistically. Phase 0 behaviour (append
a dated bullet under a `## Updates` heading) survives as the offline
fallback so the engine always makes progress.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from ..llm import DEFAULT_SONNET, LLMClient
from ..page import Page


REWRITER_SYSTEM = """\
You rewrite wiki pages to integrate NEW_INFO while preserving structure.

Rules:
  - Return ONLY the new body in markdown. No YAML frontmatter. No preamble.
  - Preserve existing [[wikilinks]] and stable section anchors.
  - If NEW_INFO contradicts a claim in the old body, keep the old claim but
    annotate the contradictory line with an HTML comment marker:
        <!-- invalid_at: YYYY-MM-DD src: <source_ref> -->
    The engine's invalidation sweep reads these.
  - Cite NEW_INFO inline with `^[<source_ref>]` at the sentence it supports.
  - Keep the tone factual. Do not editorialize.
  - If the old body does not need updating, return it unchanged.

Return the full new body. The engine will diff and rewrite summary/sources
fields separately.
"""


def rewrite(
    page: Page,
    new_info: str,
    source_ref: str,
    *,
    llm: LLMClient | None = None,
    model: str = DEFAULT_SONNET,
) -> Page:
    """Integrate NEW_INFO into `page` and return the mutated Page."""
    if llm is not None and llm.available:
        try:
            new_body = _llm_rewrite(page, new_info, source_ref, llm=llm, model=model)
            page.body = new_body.rstrip() + "\n"
            if source_ref and source_ref not in page.sources:
                page.sources.append(source_ref)
            page.updated_at = datetime.now(timezone.utc)
            return page
        except Exception:
            pass  # fall through to deterministic append
    return _append_fallback(page, new_info, source_ref)


# ── LLM path ──────────────────────────────────────────────────────────────


def _llm_rewrite(
    page: Page,
    new_info: str,
    source_ref: str,
    *,
    llm: LLMClient,
    model: str,
) -> str:
    today = date.today().isoformat()
    user = (
        f"OLD_PAGE_TITLE: {page.title}\n"
        f"PAGE_KIND: {page.kind.value}\n"
        f"TODAY: {today}\n\n"
        f"OLD_BODY:\n{page.body}\n\n"
        f"NEW_INFO (source: {source_ref}):\n{new_info.strip()}\n"
    )
    resp = llm.text_call(
        model=model,
        system=REWRITER_SYSTEM,
        user=user,
        max_tokens=4096,
    )
    return resp.text.strip() or page.body


# ── Offline fallback (Phase 0 behaviour) ──────────────────────────────────


def _append_fallback(page: Page, new_info: str, source_ref: str) -> Page:
    stamp = date.today().isoformat()
    bullet = f"- [{stamp}] {new_info.strip()} ^[{source_ref}]"

    if "## Updates" in page.body:
        lines = page.body.rstrip().splitlines()
        out: list[str] = []
        inserted = False
        for ln in lines:
            out.append(ln)
            if not inserted and ln.strip() == "## Updates":
                out.append(bullet)
                inserted = True
        page.body = "\n".join(out) + "\n"
    else:
        page.body = page.body.rstrip() + f"\n\n## Updates\n{bullet}\n"

    if source_ref and source_ref not in page.sources:
        page.sources.append(source_ref)
    return page
