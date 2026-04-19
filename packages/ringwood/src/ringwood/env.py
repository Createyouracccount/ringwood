"""Environment loading.

Philosophy:
  - Secrets (ANTHROPIC_API_KEY) NEVER live in code, config JSON, or logs.
  - Users should be able to drop a `.env` file at the wiki root OR the CWD
    and have it just work — no sourcing, no `export`, no shell rituals.
  - Already-set environment variables ALWAYS win over .env. This matters
    because the MCP server is launched by Claude Code with its own env,
    and we don't want a stray .env in ~/ringwood to override a secret
    supplied by a production secret manager.

Precedence, from highest to lowest:
  1. Real environment (parent process, OS keychain integration, etc.)
  2. `<wiki_root>/.env`   — per-wiki config
  3. `<cwd>/.env`         — per-project config
  4. `~/.config/ringwood/.env` — user-wide fallback

We deliberately do NOT read `~/.env` (too likely to leak secrets meant
for unrelated tools).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# Names we consider sensitive — they are loaded but never logged.
_SECRET_KEYS = frozenset(
    {"ANTHROPIC_API_KEY", "COHERE_API_KEY", "VOYAGE_API_KEY", "OPENAI_API_KEY"}
)


def load_env(wiki_root: str | Path | None = None) -> list[Path]:
    """Load .env files into `os.environ` without overriding existing values.

    Returns the list of files that were actually consumed, for logging.
    Missing files are silently skipped.

    Uses `python-dotenv` when available; falls back to a minimal parser so
    offline installs without the optional dep still get the common case.
    """
    candidates = _candidate_paths(wiki_root)
    loaded: list[Path] = []

    loader = _get_loader()
    for path in candidates:
        if not path.is_file():
            continue
        try:
            loader(path)
            loaded.append(path)
        except Exception as e:
            # Never let a malformed .env kill the process.
            logger.warning("skipping %s (%s)", path, e)

    if loaded:
        _log_redacted_summary(loaded)
    return loaded


def _candidate_paths(wiki_root: str | Path | None) -> list[Path]:
    out: list[Path] = []
    if wiki_root:
        out.append(Path(wiki_root).expanduser() / ".env")
    out.append(Path.cwd() / ".env")
    out.append(Path.home() / ".config" / "ringwood" / ".env")
    # Dedupe while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in out:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


def _get_loader():
    """Return a callable `(Path) -> None` that merges a .env into os.environ.

    Prefers `python-dotenv` because it handles quoting, escapes, and export
    syntax. Falls back to `_minimal_load_dotenv` which covers ~90% of cases.
    """
    try:
        from dotenv import dotenv_values  # type: ignore[import-not-found]
    except ImportError:
        return _minimal_load_dotenv

    def load(path: Path) -> None:
        for key, value in dotenv_values(path).items():
            if value is None:
                continue
            os.environ.setdefault(key, value)

    return load


def _minimal_load_dotenv(path: Path) -> None:
    """Fallback .env parser.

    Supports:
      KEY=value
      KEY="value with spaces"
      KEY='value'
      # comments and blank lines
      export KEY=value

    Does NOT support:
      variable interpolation (${OTHER})
      multi-line values
    """
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        # Strip surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _log_redacted_summary(paths: Iterable[Path]) -> None:
    """Emit one INFO line per file with secret values redacted."""
    for p in paths:
        try:
            keys = _peek_keys(p)
        except OSError:
            continue
        if not keys:
            continue
        redacted = [(k, "<redacted>" if k in _SECRET_KEYS else "set") for k in keys]
        logger.info(
            "loaded env from %s: %s",
            p,
            ", ".join(f"{k}={v}" for k, v in redacted),
        )


def _peek_keys(path: Path) -> list[str]:
    keys: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key = line.split("=", 1)[0].strip()
        if key and key.replace("_", "").isalnum():
            keys.append(key)
    return keys
