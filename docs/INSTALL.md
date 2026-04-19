# Installation

## The 30-second path

```
npx ringwood init
```

That's intended to be the entire install experience. Under the hood, the
launcher:

1. Detects a Python runner (preference order: `uvx` → `pipx` → `python3`).
2. Ensures the `ringwood-mcp` package is installed (or runs it on demand via `uvx`).
3. Creates `~/ringwood/` as the wiki root.
4. Backs up `~/.claude.json` and registers the `ringwood` MCP server.

Restart Claude Code. Done.

## Manual install (advanced)

```bash
git clone https://github.com/ringwood/ringwood
cd ringwood
uv venv
uv pip install -e packages/ringwood
uv pip install -e packages/ringwood-mcp
```

Then add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "ringwood": {
      "command": "uv",
      "args": [
        "--directory", "/abs/path/to/ringwood",
        "run", "ringwood-mcp",
        "--root", "/home/you/wiki-data"
      ]
    }
  }
}
```

## Claude.ai / Remote install (Phase 3, planned)

Once streamable-HTTP transport lands, register as a Custom Connector:

```
https://wiki.yourdomain.example/mcp
```

with OAuth scope `wiki.read wiki.write`.

## Uninstall

`npx ringwood init` always writes a timestamped backup
`~/.claude.json.bak-<epoch>`. Restore that file to remove the server entry.
Delete `~/ringwood/` to remove all wiki data.

## Doctor

```
npx ringwood doctor
```

Checks runner availability and Claude config registration; exits non-zero
if anything is broken.
