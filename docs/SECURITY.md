# Security & Secrets

ringwood never stores secrets in code, configuration JSON, or the audit log.
API keys live in `.env` files (or your real environment / secret manager)
and are read at process start.

## Where secrets live

Precedence, from highest to lowest — **the first one that has a value wins:**

| Source | When to use |
|---|---|
| **Real environment variables** (parent process, `export`, secret manager) | CI, production, anything where a manager injects env |
| `<wiki_root>/.env` — e.g. `~/ringwood/.env` | Default per-wiki config, written by `npx ringwood init` with `chmod 600` |
| `<cwd>/.env` | Per-project override when you launch the server from a repo |
| `~/.config/ringwood/.env` | User-wide fallback across multiple wikis |

A key set by the parent process **always** wins over a `.env` file. This
protects production deploys from a stray file overriding a real secret.

## Quick start

```bash
# After `npx ringwood init`, edit the template that was written for you:
$EDITOR ~/ringwood/.env
#  uncomment ANTHROPIC_API_KEY=... and paste your key
```

Restart Claude Code. That's it. The MCP server process reads `.env` on
every launch via `ringwood.env.load_env()`.

## What goes in .env

See [`.env.example`](../.env.example) for the canonical template. The keys
ringwood reads:

| Key | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Enables Haiku/Sonnet engine. Unset → offline stub mode. |
| `WIKI_HAIKU_MODEL` | Override the Haiku model alias. Default `claude-haiku-4-5`. |
| `WIKI_SONNET_MODEL` | Override the Sonnet model alias. Default `claude-sonnet-4-6`. |
| `WIKI_LLM_PROVIDER` | Force `"anthropic"` or `"stub"`. |
| `WIKI_MIN_CACHEABLE_CHARS` | Prompt-caching threshold. Default `16000` (≈Haiku floor). |
| `WIKI_ROOT` | Wiki root directory. Default `~/ringwood`. |

## What does NOT go in .env

- Wiki content. All markdown stays in `wiki/`. Commit it to git if you want
  team sharing.
- Server URLs or ports. Those are CLI flags on `ringwood-mcp`.
- Anything you'd want shared between users.

## Commit hygiene

The repo-root [`.gitignore`](../.gitignore) excludes `.env`, `.env.*`, and
`*.key`. The only allowed `.env*` file in version control is `.env.example`.
If you introduce a new backend that needs a secret, add its key name to
`.env.example` with a placeholder — never commit a real value.

## How the code enforces this

- [`ringwood.env.load_env`](../packages/ringwood/src/ringwood/env.py)
  uses `setdefault` semantics — real env always wins.
- [`AnthropicClient`](../packages/ringwood/src/ringwood/llm.py) reads
  `ANTHROPIC_API_KEY` from `os.environ` only. No direct import of a
  `secrets.py` module, no hardcoded fallbacks.
- The audit log (`wiki/log.md`) only records operation types and page ids.
  Free-text content is never written to the log.
- Stop-hook failures exit 0 with a stderr note — hooks that crash never
  block Claude Code and never leak secrets to stdout (which Claude reads).

## Reporting issues

If you find a leak path (a code path that writes a secret value to disk,
logs, or the model response), please open a GitHub issue marked
`security:` and describe the reproduction.
