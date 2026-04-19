# ringwood (launcher)

Zero-config CLI that registers [ringwood](https://github.com/Createyouracccount/ringwood)
with Claude Code and exposes its inspection commands.

```bash
npx ringwood init --with-hook
```

That's the whole install. `init` will:

1. Detect `uv`, `pipx`, or `python3` on your machine
2. Ensure the `ringwood-mcp` Python package is installed
3. Back up your `~/.claude.json` and register the MCP server
4. Optionally install the Stop-hook (`--with-hook`) so Claude answers
   get auto-captured
5. Seed `~/ringwood/.env` with `chmod 600` — fill in your Anthropic key
   (or leave blank; rule-based fallback still works)

**Restart Claude Code** and chat normally.

## What else the CLI does

```bash
npx ringwood stats              # this week's growth
npx ringwood timeline           # append-only audit log
npx ringwood diff --days 7      # pages changed in 7 days
npx ringwood list --kind concept
npx ringwood show <page_id>
npx ringwood lint               # broken links, stale, orphans
npx ringwood doctor             # diagnose a broken install
npx ringwood path               # print the wiki root
npx ringwood serve [args…]      # run the MCP server directly
```

All subcommands after the first three are transparent pass-throughs to the
Python `ringwood-cli` entry point shipped by `ringwood-mcp`.

## What it does NOT do

- It does not transmit your data anywhere. Everything is local markdown
  under `~/ringwood/`.
- It does not read `~/.env` (too likely to leak unrelated secrets). It
  only reads `~/ringwood/.env`, the CWD's `.env`, or
  `~/.config/ringwood/.env`. Real env vars always win.
- It does not phone home. There is no telemetry.

## Full documentation

[github.com/Createyouracccount/ringwood](https://github.com/Createyouracccount/ringwood)

## License

MIT.
