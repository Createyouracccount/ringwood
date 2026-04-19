"""Resource registrations.

Clients that prefer MCP resources (vs tool calls) can fetch pages via
`wiki://article/<page_id>`. The page_id can contain slashes — FastMCP treats
the URI template as a single capturing segment after the last known prefix.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ringwood import Wiki
from ringwood.storage.base import PageNotFound


def register_resources(mcp: FastMCP, wiki: Wiki) -> None:

    @mcp.resource("wiki://article/{page_id}")
    async def article(page_id: str) -> str:
        """Return the markdown body of a wiki article."""
        try:
            page = wiki.get(page_id)
        except PageNotFound:
            raise LookupError(f"article not found: {page_id!r}")
        return page.to_markdown()

    @mcp.resource("wiki://log")
    async def log() -> str:
        """Return the audit log (log.md). Useful for `wiki timeline`-style UIs."""
        return wiki.storage.read_log() or "(empty)"
