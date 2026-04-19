"""Contextual Retrieval prefix generation (Anthropic, 2024).

A 50-100 token prefix prepended to the indexed text of each page. Drops
top-20 retrieval failure rate from 5.7% to 2.9% (Contextual BM25 alone).

Phase 1 uses Haiku with prompt caching on the document block: the first call
pays 1.25x write cost, subsequent chunks of the same document pay 0.1x read.
When no API key is available, the Phase 0 heuristic still produces a useful
prefix so indexing never breaks.

Reference: https://www.anthropic.com/news/contextual-retrieval
"""

from __future__ import annotations

import re

from ..llm import DEFAULT_HAIKU, LLMClient


CONTEXTUALIZE_SYSTEM = """\
You write one-line retrieval prefixes that situate a specific chunk within a
larger document, for the purpose of improving full-text and semantic search.

Output 50 to 100 tokens of plain prose. No bullet points. No lead-ins such as
"This chunk ..." or "Here is ...". Begin with the topic itself. End with a
period. Do not repeat the chunk verbatim — describe its role.

Output ONLY the prefix. No preamble, no markdown, no quotes.
"""


def contextualize(
    title: str,
    body: str,
    *,
    llm: LLMClient | None = None,
    model: str = DEFAULT_HAIKU,
    document: str | None = None,
    max_tokens: int = 180,
) -> str:
    """Return a 50-100 token Contextual Retrieval prefix.

    When `document` is provided and the LLM is available, the document is
    cached as part of the system prompt — the first call pays write cost,
    subsequent chunks of the same document pay 0.1x.
    """
    if llm is not None and llm.available:
        try:
            return _llm_contextualize(
                title=title, body=body, document=document, llm=llm, model=model,
                max_tokens=max_tokens,
            )
        except Exception:
            # Contextualization is best-effort. Never block ingest on LLM failure.
            pass
    return _heuristic(title, body)


def _llm_contextualize(
    *,
    title: str,
    body: str,
    document: str | None,
    llm: LLMClient,
    model: str,
    max_tokens: int,
) -> str:
    system = CONTEXTUALIZE_SYSTEM
    cache = False
    if document:
        # Put the document in the cacheable portion of the system prompt.
        # All chunks of the same document share the same system text → cache hit.
        system = (
            f"{CONTEXTUALIZE_SYSTEM}\n\n"
            f"<document title={title!r}>\n{document}\n</document>\n"
        )
        cache = True

    user = (
        f"Title: {title}\n\n"
        f"<chunk>\n{body}\n</chunk>\n\n"
        f"Write the retrieval prefix."
    )
    resp = llm.text_call(
        model=model,
        system=system,
        user=user,
        max_tokens=max_tokens,
        cache_system=cache,
    )
    text = resp.text.strip().strip('"').strip()
    return text or _heuristic(title, body)


# ── Heuristic fallback ────────────────────────────────────────────────────

_SENT_END = re.compile(r"(?<=[.!?。?!])\s+")


def _heuristic(title: str, body: str) -> str:
    """Cheap deterministic prefix. Still helps BM25 by pinning the title into
    the indexed text even when the body drifts into detail."""
    if not body.strip():
        return title
    first_para = body.strip().split("\n\n", 1)[0]
    parts = _SENT_END.split(first_para, maxsplit=1)
    first_sent = parts[0].strip() if parts else first_para
    summary = f"{title}. {first_sent}".strip()
    return summary[:400]  # ~100 tokens
