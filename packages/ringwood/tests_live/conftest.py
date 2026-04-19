"""Shared fixtures for live tests that hit the real Claude API.

These tests are gated behind an explicit ANTHROPIC_API_KEY check. Pure
offline runs (CI without secrets) skip everything here automatically.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from ringwood import Wiki
from ringwood.env import load_env


def _has_key() -> bool:
    # Load from ~/ringwood/.env if real env is empty — lets devs run
    # `pytest tests_live/` without a manual export step.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        load_env(Path.home() / "ringwood")
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


skip_without_key = pytest.mark.skipif(
    not _has_key(),
    reason="ANTHROPIC_API_KEY not set — skipping live API test",
)


@pytest.fixture
def live_wiki(tmp_path: Path) -> Wiki:
    """A fresh wiki bound to a real AnthropicClient."""
    if not _has_key():
        pytest.skip("ANTHROPIC_API_KEY required")
    wiki = Wiki(root=tmp_path)
    assert wiki.llm.available, "Expected AnthropicClient but got StubClient"
    return wiki


@pytest.fixture(autouse=True)
def _propagate_key(monkeypatch):
    """Ensure the .env-loaded key survives monkeypatching in sibling tests."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        monkeypatch.setenv("ANTHROPIC_API_KEY", os.environ["ANTHROPIC_API_KEY"])
