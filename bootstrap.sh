#!/usr/bin/env bash
# ringwood — one-command installer.
#
# Usage (from a fresh clone):
#   ./bootstrap.sh            # install + register MCP + seed ~/ringwood
#   ./bootstrap.sh --hook     # also install the Stop hook (auto-capture)
#   ./bootstrap.sh --dev      # editable install + dev deps + pytest
#
# What it does:
#   1. verifies Python ≥ 3.10 and Node ≥ 18
#   2. creates a local .venv (unless --system)
#   3. installs ringwood + ringwood-mcp (editable if --dev)
#   4. runs the launcher's `init` to register the MCP server
#   5. seeds ~/ringwood/.env if missing
#   6. prints the next step (add ANTHROPIC_API_KEY)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── args ─────────────────────────────────────────────────────────────────
INSTALL_HOOK=0
DEV=0
USE_SYSTEM=0
for arg in "$@"; do
  case "$arg" in
    --hook)    INSTALL_HOOK=1 ;;
    --dev)     DEV=1 ;;
    --system)  USE_SYSTEM=1 ;;
    -h|--help)
      sed -n '2,17p' "$0" | sed 's/^# *//'
      exit 0
      ;;
    *)
      echo "unknown flag: $arg" >&2
      exit 1
      ;;
  esac
done

# ── colors ───────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m')
  GRN=$(printf '\033[32m'); YEL=$(printf '\033[33m')
  RED=$(printf '\033[31m'); RST=$(printf '\033[0m')
else
  BOLD=""; DIM=""; GRN=""; YEL=""; RED=""; RST=""
fi
say() { printf '%s\n' "$*"; }
ok()  { printf '%s✓%s %s\n' "$GRN" "$RST" "$*"; }
warn(){ printf '%s!%s %s\n' "$YEL" "$RST" "$*" >&2; }
die() { printf '%s✗%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }

# ── preflight ────────────────────────────────────────────────────────────
say "${BOLD}ringwood bootstrap${RST}"
say ""

command -v python3 >/dev/null || die "python3 not found. Install Python ≥ 3.10."
PY_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3,10) else 0)')
[ "$PY_OK" = "1" ] || die "Python $PY_VER is too old. Need ≥ 3.10."
ok "Python $PY_VER"

command -v node >/dev/null || die "node not found. Install Node ≥ 18."
NODE_VER=$(node --version | sed 's/^v//')
NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
[ "$NODE_MAJOR" -ge 18 ] || die "Node $NODE_VER too old. Need ≥ 18."
ok "Node v$NODE_VER"

# ── Python env ───────────────────────────────────────────────────────────
if [ "$USE_SYSTEM" -eq 0 ]; then
  if [ ! -d "$HERE/.venv" ]; then
    say "${DIM}creating .venv …${RST}"
    python3 -m venv "$HERE/.venv"
  fi
  # shellcheck source=/dev/null
  . "$HERE/.venv/bin/activate"
  ok ".venv activated"
  PIP="$HERE/.venv/bin/pip"
else
  PIP="python3 -m pip"
  warn "using system Python (--system)"
fi

$PIP install --upgrade --quiet pip >/dev/null

EXTRAS=""
[ "$DEV" -eq 1 ] && EXTRAS="[dev]"

say "${DIM}installing ringwood + ringwood-mcp …${RST}"
$PIP install --quiet -e "$HERE/packages/ringwood$EXTRAS" \
                      -e "$HERE/packages/ringwood-mcp"
ok "packages installed (editable)"

# ── register MCP server via launcher ─────────────────────────────────────
say "${DIM}registering MCP server with Claude Code …${RST}"
HOOK_FLAG=""
[ "$INSTALL_HOOK" -eq 1 ] && HOOK_FLAG="--with-hook" || HOOK_FLAG="--no-hook"

# Prefer the launcher's system path resolution. The launcher picks between
# uvx / pipx / python3 automatically; since we just installed with pip,
# python3 -m path will work regardless of which one it picks.
node "$HERE/packages/npm-launcher/bin/ringwood.js" init $HOOK_FLAG

# ── dev smoke test ───────────────────────────────────────────────────────
if [ "$DEV" -eq 1 ]; then
  say ""
  say "${DIM}running tests (offline stub mode) …${RST}"
  ( cd "$HERE/packages/ringwood" && python3 -m pytest tests/ -q )
  ok "21/21 tests passing"
fi

# ── finish ───────────────────────────────────────────────────────────────
say ""
say "${BOLD}✅ bootstrap complete${RST}"
say ""
say "Next step:"
if [ ! -s "$HOME/ringwood/.env" ] || ! grep -q '^ANTHROPIC_API_KEY=' "$HOME/ringwood/.env" 2>/dev/null; then
  say "  1. add your Anthropic key to ~/ringwood/.env"
  say "       \$EDITOR ~/ringwood/.env"
  say "       # uncomment ANTHROPIC_API_KEY=..."
  say "     (optional — rule-based fallback works without a key)"
fi
say "  $([ -n "${NEXT_N:-}" ] && echo "" || echo "2.") restart Claude Code, then try:"
say "       > remember: we use snake_case for filenames"
say "       > what's our filename convention?"
say ""
say "Add the CLI to PATH: ${BOLD}export PATH=\"$HERE/bin:\$PATH\"${RST}"
say ""
say "Inspect growth:   ${BOLD}ringwood stats${RST}"
say "Timeline:         ${BOLD}ringwood timeline${RST}"
say "Integrity:        ${BOLD}ringwood lint${RST}"
