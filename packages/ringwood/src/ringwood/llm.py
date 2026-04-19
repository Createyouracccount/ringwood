"""LLM client abstraction.

Two backends live behind a single interface:

    * `AnthropicClient` — real Haiku / Sonnet calls. Used in production.
    * `StubClient`       — deterministic fallback used when no API key is
                            configured. Phase 0 behaviour, preserved so
                            smoke tests and offline users still work.

The engine modules never import `anthropic` directly; they ask `get_client()`
for whatever is available. Tests inject a `StubClient` to avoid network.

Design anchors:
  - No global singletons. The `Wiki` instance owns a client.
  - Sync and async both work; the engine calls the sync façade which is a
    thin wrapper. This keeps adapters (MCP server, LangChain tools) simple.
  - Prompt caching for Contextual Retrieval is a first-class concern —
    see `structured_call` / `text_call` `cache_system` parameter.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol, Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────

# Defaults per PLAN §4 "Model cost discipline". Override via env or Wiki(..., llm=...).
DEFAULT_HAIKU = os.environ.get("WIKI_HAIKU_MODEL", "claude-haiku-4-5")
DEFAULT_SONNET = os.environ.get("WIKI_SONNET_MODEL", "claude-sonnet-4-6")

# Minimum prefix to make prompt caching worthwhile (Haiku 4.5 floor = 4096 tokens).
# Below this we skip the cache_control marker entirely to avoid paying the 1.25x
# write premium for nothing.
MIN_CACHEABLE_CHARS = int(os.environ.get("WIKI_MIN_CACHEABLE_CHARS", "16000"))

T = TypeVar("T", bound=BaseModel)


# ── Return types ──────────────────────────────────────────────────────────


@dataclass
class LLMUsage:
    """Token accounting per call. Surfaces cache efficiency to the user."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_input_tokens > 0


@dataclass
class TextResponse:
    text: str
    usage: LLMUsage


@dataclass
class StructuredResponse[T]:
    parsed: T | None           # None on refusal / parse failure — caller must guard
    raw_text: str
    usage: LLMUsage
    stop_reason: str | None = None


# ── Client protocol ───────────────────────────────────────────────────────


class LLMClient(Protocol):
    """What the engine needs. Two implementations live below."""

    def text_call(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 1024,
        cache_system: bool = False,
    ) -> TextResponse: ...

    def structured_call(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: Type[T],
        max_tokens: int = 1024,
        cache_system: bool = False,
    ) -> StructuredResponse[T]: ...

    @property
    def available(self) -> bool:
        """True iff this client can actually make network calls.

        The engine uses this to decide whether to fall back to the Phase 0
        stub when the caller asked for "Anthropic" but there's no key.
        """
        ...


# ── Stub client (Phase 0 offline fallback) ────────────────────────────────


class StubClient:
    """Deterministic placeholder. Engine logic still runs; quality comes from
    rule-based fallbacks in each module. Unit tests run against this.
    """

    available = False  # tells the engine to use its rule-based fallback

    def text_call(self, **_: Any) -> TextResponse:
        raise RuntimeError(
            "StubClient.text_call called — engine should check .available first"
        )

    def structured_call(self, **_: Any) -> StructuredResponse[Any]:
        raise RuntimeError(
            "StubClient.structured_call called — engine should check .available first"
        )


# ── Anthropic client ──────────────────────────────────────────────────────


class AnthropicClient:
    """Real Claude calls. Instantiated lazily so the `anthropic` import is
    optional for offline users.
    """

    def __init__(self, api_key: str | None = None) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "anthropic package is not installed. "
                "Run `pip install anthropic>=0.96` or use StubClient."
            ) from e
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    @property
    def available(self) -> bool:
        return bool(self._client.api_key)

    # ── Text ────────────────────────────────────────────────────────────

    def text_call(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 1024,
        cache_system: bool = False,
    ) -> TextResponse:
        system_payload = _build_system(system, cache=cache_system)
        resp = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_payload,
            messages=[{"role": "user", "content": user}],
            temperature=0,
        )
        text = _extract_text(resp)
        return TextResponse(text=text, usage=_extract_usage(resp))

    # ── Structured ──────────────────────────────────────────────────────

    def structured_call(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: Type[T],
        max_tokens: int = 1024,
        cache_system: bool = False,
    ) -> StructuredResponse[T]:
        """Prefer `messages.parse` when the SDK supports it; fall back to the
        forced-tool pattern otherwise. Both paths return a validated Pydantic
        instance or None on refusal / parse failure.
        """
        system_payload = _build_system(system, cache=cache_system)

        parse = getattr(self._client.messages, "parse", None)
        if parse is not None:
            try:
                resp = parse(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_payload,
                    messages=[{"role": "user", "content": user}],
                    output_format=schema,
                    temperature=0,
                )
                parsed = getattr(resp, "parsed_output", None) or getattr(resp, "parsed", None)
                if parsed is not None and not isinstance(parsed, schema):
                    parsed = schema.model_validate(parsed)
                return StructuredResponse(
                    parsed=parsed,
                    raw_text=_extract_text(resp),
                    usage=_extract_usage(resp),
                    stop_reason=getattr(resp, "stop_reason", None),
                )
            except Exception as e:
                logger.warning("messages.parse failed (%s); falling back to forced tool", e)

        return self._structured_via_forced_tool(
            model=model,
            system_payload=system_payload,
            user=user,
            schema=schema,
            max_tokens=max_tokens,
        )

    def _structured_via_forced_tool(
        self,
        *,
        model: str,
        system_payload: list,
        user: str,
        schema: Type[T],
        max_tokens: int,
    ) -> StructuredResponse[T]:
        """Universal fallback: ask Claude to call a single tool whose schema
        matches the Pydantic model. Works on every SDK version from 0.39+.
        """
        json_schema = schema.model_json_schema()
        tool_name = f"emit_{schema.__name__.lower()}"
        tool = {
            "name": tool_name,
            "description": (schema.__doc__ or f"Return a {schema.__name__}.").strip(),
            "input_schema": json_schema,
        }
        resp = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_payload,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name},
            temperature=0,
        )
        parsed: T | None = None
        raw_text = ""
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                raw_text = json.dumps(block.input, ensure_ascii=False)
                try:
                    parsed = schema.model_validate(block.input)
                except ValidationError as e:
                    logger.warning("structured output failed validation: %s", e)
                    parsed = None
                break
            if getattr(block, "type", None) == "text":
                raw_text = raw_text or block.text
        return StructuredResponse(
            parsed=parsed,
            raw_text=raw_text,
            usage=_extract_usage(resp),
            stop_reason=getattr(resp, "stop_reason", None),
        )


# ── Builders / helpers ────────────────────────────────────────────────────


def _build_system(system: str, *, cache: bool) -> list[dict]:
    """Render the system prompt as the multi-block format Anthropic expects.

    Cache markers are only attached to content that crosses the minimum
    cacheable length — attaching them to short prompts just burns the 1.25x
    write premium with no read benefit.
    """
    block: dict[str, Any] = {"type": "text", "text": system}
    if cache and len(system) >= MIN_CACHEABLE_CHARS:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def _extract_text(resp: Any) -> str:
    content = getattr(resp, "content", None)
    if not content:
        return ""
    for block in content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _extract_usage(resp: Any) -> LLMUsage:
    u = getattr(resp, "usage", None)
    if u is None:
        return LLMUsage()
    return LLMUsage(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
    )


# ── Factory ───────────────────────────────────────────────────────────────


def get_client(prefer: str | None = None) -> LLMClient:
    """Return the best available client.

    Selection order:
      1. explicit `prefer` arg ("anthropic" or "stub")
      2. ANTHROPIC_API_KEY in env → AnthropicClient
      3. otherwise StubClient

    Callers never catch ImportError here; they just check `.available`.
    """
    prefer = (prefer or os.environ.get("WIKI_LLM_PROVIDER", "")).lower()
    if prefer == "stub":
        return StubClient()
    if prefer == "anthropic" or os.environ.get("ANTHROPIC_API_KEY"):
        try:
            client = AnthropicClient()
            if client.available:
                return client
        except RuntimeError as e:
            logger.info("Anthropic client unavailable (%s); using StubClient", e)
    return StubClient()
