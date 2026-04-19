"""Live end-to-end: Claude Code-style MCP client talks to our server, which
talks to the real Anthropic API. Proves the full Phase 1 path works.

If this passes, `npx ringwood init` + restart Claude Code works.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from .conftest import skip_without_key


@skip_without_key
@pytest.mark.asyncio
async def test_end_to_end_mcp_with_live_llm(tmp_path: Path):
    """Spawn the server as Claude Code would, drive it via stdio JSON-RPC."""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    server_root = tmp_path / "wiki"
    server_root.mkdir()

    # Propagate ANTHROPIC_API_KEY into the subprocess — .env resolution only
    # looks at server_root (fresh tmpdir with no .env), so we must pass the
    # key explicitly.
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ringwood_mcp.server", "--root", str(server_root)],
        env={**os.environ},
    )

    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()

            # 1) ingest — Haiku classifier + Sonnet decision kick in.
            r1 = await session.call_tool(
                "ingest_source",
                {
                    "text": "우리 팀 백엔드 컨벤션은 snake_case 함수명을 쓴다.",
                    "source_ref": "team-convention.md",
                    "title": "백엔드 네이밍 컨벤션",
                    "kind": "decision",
                },
            )
            payload1 = json.loads(r1.content[0].text)
            assert payload1["operation"] in {"ADD", "UPDATE", "NOOP"}
            assert payload1["page_id"], "page_id missing from ingest response"

            # 2) re-ingest a NOOP-style paraphrase.
            r2 = await session.call_tool(
                "ingest_source",
                {
                    "text": "백엔드 네이밍은 snake_case 함수명이 우리 컨벤션이야.",
                    "source_ref": "team-convention.md",
                    "title": "네이밍 컨벤션",
                    "kind": "decision",
                },
            )
            payload2 = json.loads(r2.content[0].text)
            # NOOP or UPDATE both acceptable; ADD would suggest duplicate-blind.
            assert payload2["operation"] in {"NOOP", "UPDATE"}, (
                f"duplicate-blind ADD produced: {payload2}"
            )

            # 3) search via MCP surface.
            r3 = await session.call_tool(
                "search_wiki", {"query": "백엔드 네이밍", "limit": 3}
            )
            payload3 = json.loads(r3.content[0].text)
            assert payload3["hits"], "search returned empty on seeded wiki"
            assert "📚" in payload3["citation_footer"], "citation footer missing"
