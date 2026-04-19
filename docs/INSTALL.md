# Installation

## Current path — clone + bootstrap (pre-release)

```bash
git clone https://github.com/Createyouracccount/ringwood
cd ringwood
./bootstrap.sh --hook
```

`bootstrap.sh`:

1. Verifies Python ≥ 3.10 and Node ≥ 18.
2. Creates `.venv` and editable-installs `ringwood` + `ringwood-mcp`.
3. Runs the launcher, which detects the local install on PATH and records
   its **absolute path** in `~/.claude.json` (so Claude Code can spawn the
   server even without our venv being active).
4. Optionally installs the Stop hook (`--hook`) so Q&A is auto-captured.
5. Seeds `~/ringwood/.env` (chmod 600) for your API key.

Restart Claude Code, then `claude mcp list` should show
`ringwood: ✓ Connected`.

## Future path (after PyPI release)

```
npx ringwood init
```

Launcher detection order:

1. Pre-installed `ringwood-mcp` on PATH (contributors who cloned).
2. `uvx --from ringwood-mcp` — downloads from PyPI on demand.
3. `pipx install ringwood-mcp` — persistent install.
4. `python3 -m pip install --user ringwood-mcp` — fallback.

## Manual install (advanced)

```bash
git clone https://github.com/Createyouracccount/ringwood
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
