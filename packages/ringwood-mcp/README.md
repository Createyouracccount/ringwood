# ringwood-mcp

MCP server that exposes [ringwood](https://pypi.org/project/ringwood/)
to any Model-Context-Protocol client: Claude Code, Claude.ai (Custom
Connectors), Cursor, Windsurf, Zed.

**Most users should use the [ringwood launcher](https://github.com/ringwood/ringwood)
instead of installing this package directly.** The launcher handles
registration, the `.env` template, and the Stop-hook wiring.

## Install

```bash
pipx install ringwood-mcp
# or
uv tool install ringwood-mcp
# or on demand:
uvx --from ringwood-mcp ringwood-mcp --root ~/my-wiki
```

## What it ships

Three entry points:

| Command | Purpose |
|---|---|
| `ringwood-mcp` | The MCP server (stdio by default, HTTP via `--mode http`) |
| `ringwood-capture` | Claude Code Stop-hook target — records the last turn |
| `ringwood-cli` | Visibility: `stats / timeline / diff / list / show / lint` |

## MCP surface

Six tools, two resource templates:

| Tool | What it does |
|---|---|
| `search_wiki` | Hybrid BM25, returns hits + citation footer |
| `get_article` | Full markdown for a page id |
| `ingest_source` | Add/update via the decision engine |
| `record_answer` | Classifier-gated file (used by the Stop hook) |
| `list_recent_changes` | Week/month summary |
| `lint_wiki` | Broken links, stale, orphans |

| Resource | URI |
|---|---|
| A wiki article | `wiki://article/{page_id}` |
| The audit log | `wiki://log` |

## Register with Claude Code

```json
{
  "mcpServers": {
    "ringwood": {
      "command": "uvx",
      "args": ["--from", "ringwood-mcp", "ringwood-mcp", "--root", "~/ringwood"]
    }
  }
}
```

(The launcher writes this for you.)

## License

MIT. See [main README](https://github.com/ringwood/ringwood#readme) for
docs, A/B quality numbers, and troubleshooting.
