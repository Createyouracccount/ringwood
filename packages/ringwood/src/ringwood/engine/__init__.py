"""Compounding engine — the Anthropic-powered brain.

Phase 0 ships stubs. Phase 1 wires in real Anthropic API calls:
  - classifier.py    — Haiku: is this Q&A worth saving?
  - contextualize.py — Haiku: generate 50-100 token retrieval prefix
  - decision.py      — Sonnet: ADD/UPDATE/DELETE/NOOP
  - rewriter.py      — Sonnet: integrate NEW_INFO into existing page
  - lint.py          — nightly sweep (broken links, stale, orphans)

Each module exposes a small, testable function. The Wiki API composes them.
"""
