"""FastMCP server wiring.

Single entry point `main()` picks transport from env/CLI:
  WIKI_MCP_MODE=stdio   (default)
  WIKI_MCP_MODE=http    — streamable HTTP for Claude.ai / remote

PLAN alignment:
  - 6 tools (PLAN §6). Kept well under Anthropic's 5-15 ceiling to avoid
    tool-search overhead.
  - One resource pattern (wiki://article/{page_id}) so clients that prefer
    resource URIs (e.g. Claude Desktop preview) can still read pages.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ringwood import Wiki

from .tools import register_tools
from .resources import register_resources


def build_server(root: Path, *, mode: str = "stdio") -> FastMCP:
    """Compose a FastMCP server with our tools/resources pre-registered."""
    wiki = Wiki(root=root)

    kwargs: dict = {}
    if mode == "http":
        kwargs.update(stateless_http=True, json_response=True)

    mcp = FastMCP(
        "ringwood",
        instructions=(
            "A compounding knowledge wiki. Call search_wiki before answering "
            "domain questions. Call record_answer after answering anything "
            "worth remembering."
        ),
        **kwargs,
    )
    register_tools(mcp, wiki)
    register_resources(mcp, wiki)
    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="ringwood-mcp")
    parser.add_argument(
        "--root",
        default=os.environ.get("WIKI_ROOT", "./wiki-data"),
        help="wiki root directory (default: ./wiki-data or $WIKI_ROOT)",
    )
    parser.add_argument(
        "--mode",
        choices=("stdio", "http"),
        default=os.environ.get("WIKI_MCP_MODE", "stdio"),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    mcp = build_server(root, mode=args.mode)

    if args.mode == "http":
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path="/mcp",
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
