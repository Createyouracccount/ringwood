"""capture-last-turn — the target of Claude Code's Stop hook.

Called once per conversation turn end. Reads the Stop-hook JSON payload from
stdin, extracts the final (user_prompt, assistant_response) pair from the
transcript, and asks wiki.record_answer() to decide whether to file it.

Contract with Claude Code hooks:
  - Payload on stdin (JSON object):
      session_id, transcript_path, cwd, hook_event_name, last_assistant_message
  - Exit 0 on success. NEVER exit 2 — that would block Claude's Stop event.
  - Any error goes to stderr; we still exit 0 so hooks stay non-blocking.

Design:
  - This runs in a subprocess on every Stop. It MUST be fast and quiet.
  - No Anthropic calls synchronously here; the save happens through the
    wiki, which will use whatever client is configured (stub in the common
    offline case → cheap regex classifier → usually returns "don't save").
  - When the classifier rejects (~90% of the time), total latency is <50ms.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from ringwood import Wiki


def main() -> None:
    parser = argparse.ArgumentParser(prog="ringwood-capture")
    parser.add_argument(
        "--root",
        default=os.environ.get("WIKI_ROOT"),
        help="wiki root (defaults to $WIKI_ROOT, falls back to ~/ringwood)",
    )
    args = parser.parse_args()

    root = Path(args.root or os.path.expanduser("~/ringwood")).resolve()

    try:
        payload = _read_stdin_json()
    except Exception as e:
        _fail_silently(f"could not parse hook payload: {e}")
        return

    assistant = payload.get("last_assistant_message", "").strip()
    if not assistant:
        # Nothing to record. Happens on empty / tool-only turns.
        return

    user_prompt = _extract_last_user_prompt(payload.get("transcript_path"))

    try:
        wiki = Wiki(root=root)
        result = wiki.record_answer(question=user_prompt, answer=assistant)
    except Exception as e:
        # Exit 0 so we don't block Claude Code's Stop event, but emit a
        # systemMessage the user can actually see — a silent failure that
        # loses a capture is worse than a one-line warning. Include the
        # exception type (not the full repr, which can leak request URLs).
        _fail_silently(f"record_answer failed: {type(e).__name__}: {e}")
        try:
            json.dump(
                {"systemMessage": f"[ringwood] capture skipped: {type(e).__name__}"},
                sys.stdout,
            )
        except Exception:
            pass
        return

    # Stdout is consumed by Claude Code. We can emit an optional JSON with a
    # terse systemMessage so the user sees a one-line breadcrumb when the
    # wiki actually captured something. Nothing on skip (keeps the transcript
    # clean).
    if result is not None:
        out = {
            "systemMessage": f"🧠 wiki ← {result.operation.value} {result.page_id}",
        }
        json.dump(out, sys.stdout)


# ── helpers ───────────────────────────────────────────────────────────────


def _read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def _extract_last_user_prompt(transcript_path: str | None) -> str:
    """Scan the session JSONL from the bottom and return the last user turn.

    Robust to missing files and to schema variance — Claude Code has shifted
    the transcript schema over releases. We accept several shapes.
    """
    if not transcript_path:
        return ""
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return ""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        text = _pluck_user_text(entry)
        if text:
            return text.strip()
    return ""


def _pluck_user_text(entry: dict) -> str:
    """Normalize a transcript line into a user prompt string, or ''."""
    if entry.get("role") == "user" or entry.get("type") == "user":
        return _stringify_content(entry.get("content") or entry.get("message") or "")
    msg = entry.get("message")
    if isinstance(msg, dict) and msg.get("role") == "user":
        return _stringify_content(msg.get("content") or "")
    return ""


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text", "")))
        return "\n".join(p for p in parts if p)
    return ""


def _fail_silently(msg: str) -> None:
    """Stop hook failures must never block Claude. Log to stderr and exit 0."""
    print(f"[ringwood capture] {msg}", file=sys.stderr)


if __name__ == "__main__":
    main()
