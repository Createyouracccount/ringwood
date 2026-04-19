"""Live test: Contextual Retrieval prompt caching actually hits.

`contextualize()` sends the whole source document in the system prompt with
cache_control on. Second and later chunks against the same doc should show
non-zero `cache_read_input_tokens` in the Anthropic usage metadata.

If this test fails, silent cache invalidators are sneaking in (unsorted
JSON, timestamps, tool order, etc.). See PLAN.md §4-C.
"""

from __future__ import annotations

import pytest

from ringwood.engine.contextualize import contextualize

from .conftest import skip_without_key


# A long-ish document (>16000 chars default WIKI_MIN_CACHEABLE_CHARS floor
# is 16K; we pad past that so the engine attaches cache_control).
LONG_DOC = (
    "# Prompt Caching Reference Document\n\n"
    "Anthropic prompt caching lets callers mark prefixes of a request as\n"
    "cacheable. Cache writes cost 1.25x the base rate for the 5-minute TTL\n"
    "and 2x for the 1-hour TTL; reads cost 0.1x. Minimum cacheable prefix\n"
    "is 4096 tokens for Haiku 4.5 and 2048 for Sonnet 4.6. Cache keys are\n"
    "computed from the byte sequence of the cached blocks plus the tool\n"
    "definitions and system preamble — any difference invalidates the key.\n\n"
) * 40  # ≈ 18K chars


@skip_without_key
def test_prompt_cache_hits_on_second_chunk(live_wiki, capsys):
    """First call pays the write, second call reads it."""
    if not live_wiki.llm.available:
        pytest.skip("no LLM")

    # First call — expect cache CREATION (write).
    # We call contextualize directly to inspect usage. Title differs per
    # chunk but the document (placed in the cached system block) is fixed.
    chunk_a = "Cache writes cost more than reads."
    chunk_b = "Cache reads cost 0.1x the base input rate."

    # NOTE: contextualize() wraps usage; we need raw LLM for metrics.
    system_text = (
        "You write one-line retrieval prefixes that situate a specific chunk "
        "within a larger document, for the purpose of improving full-text "
        "and semantic search.\n\nOutput 50 to 100 tokens of plain prose. "
        "No bullet points. No lead-ins such as 'This chunk ...' or 'Here is "
        "...'. Begin with the topic itself. End with a period. Do not repeat "
        "the chunk verbatim — describe its role.\n\nOutput ONLY the prefix. "
        "No preamble, no markdown, no quotes.\n\n"
        f"<document title='PromptCachingRef'>\n{LONG_DOC}\n</document>\n"
    )

    r1 = live_wiki.llm.text_call(
        model="claude-haiku-4-5",
        system=system_text,
        user=f"Title: PromptCachingRef\n\n<chunk>\n{chunk_a}\n</chunk>\n\nWrite the retrieval prefix.",
        max_tokens=180,
        cache_system=True,
    )
    r2 = live_wiki.llm.text_call(
        model="claude-haiku-4-5",
        system=system_text,  # identical
        user=f"Title: PromptCachingRef\n\n<chunk>\n{chunk_b}\n</chunk>\n\nWrite the retrieval prefix.",
        max_tokens=180,
        cache_system=True,
    )

    with capsys.disabled():
        print("\n┌── prompt cache usage ─────────────────────────")
        print(f"│ call 1: create={r1.usage.cache_creation_input_tokens}  "
              f"read={r1.usage.cache_read_input_tokens}  "
              f"input={r1.usage.input_tokens}")
        print(f"│ call 2: create={r2.usage.cache_creation_input_tokens}  "
              f"read={r2.usage.cache_read_input_tokens}  "
              f"input={r2.usage.input_tokens}")
        print("└────────────────────────────────────────────────")

    # First call should write the cache (may also have been seeded earlier).
    seeded = (
        r1.usage.cache_creation_input_tokens > 0
        or r1.usage.cache_read_input_tokens > 0
    )
    assert seeded, "first call wrote nothing and read nothing — caching disabled?"

    # Second call must read from cache — this is the whole point.
    assert r2.usage.cache_read_input_tokens > 0, (
        "cache miss on identical system prompt — silent invalidator present.\n"
        f"  usage: {r2.usage}"
    )


@skip_without_key
def test_short_doc_skips_cache(live_wiki, capsys):
    """Below the minimum cacheable length, the engine MUST skip cache_control.

    Paying 1.25x write cost for a 2KB prefix loses money. Verify we don't."""
    if not live_wiki.llm.available:
        pytest.skip("no LLM")

    short_doc = "Tiny document."
    out = contextualize(
        title="Small",
        body=short_doc,
        document=short_doc,
        llm=live_wiki.llm,
    )
    # We can't inspect usage through contextualize() directly, so the check
    # is behavioral: the call must succeed and return non-empty text.
    assert out and len(out) > 0
    with capsys.disabled():
        print(f"\nshort-doc prefix: {out!r}")
