"""Tests for .env loading behavior.

Security invariants (MUST hold):
  1. Real environment variables win over .env files.
  2. .env files outside the recognized search paths are ignored.
  3. Malformed .env files are skipped, not fatal.
  4. Secret values never appear in return values (only paths).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ringwood.env import load_env


@pytest.fixture
def clean_env(monkeypatch):
    """Wipe every var our tests touch, then restore on teardown."""
    for key in ("ANTHROPIC_API_KEY", "WIKI_HAIKU_MODEL", "WIKI_TEST_VAR"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_loads_wiki_root_env(tmp_path: Path, clean_env):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-from-root\nWIKI_TEST_VAR=hi\n")
    loaded = load_env(tmp_path)
    assert env_file in loaded
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-from-root"
    assert os.environ["WIKI_TEST_VAR"] == "hi"


def test_real_env_wins_over_dotenv(tmp_path: Path, clean_env):
    """If the process already has a var set, .env must NOT override."""
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-already-set")
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-from-file\n")
    load_env(tmp_path)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-already-set"


def test_quoted_values(tmp_path: Path, clean_env):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'ANTHROPIC_API_KEY="sk-with-spaces and-stuff"\n'
        "WIKI_TEST_VAR='single-quoted'\n"
    )
    load_env(tmp_path)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-with-spaces and-stuff"
    assert os.environ["WIKI_TEST_VAR"] == "single-quoted"


def test_export_prefix_tolerated(tmp_path: Path, clean_env):
    env_file = tmp_path / ".env"
    env_file.write_text("export ANTHROPIC_API_KEY=sk-exported\n")
    load_env(tmp_path)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-exported"


def test_comments_and_blanks_ignored(tmp_path: Path, clean_env):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# header comment\n"
        "\n"
        "ANTHROPIC_API_KEY=sk-1\n"
        "   # indented comment\n"
        "WIKI_TEST_VAR=two\n"
    )
    load_env(tmp_path)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-1"
    assert os.environ["WIKI_TEST_VAR"] == "two"


def test_missing_file_is_silent(tmp_path: Path, clean_env):
    loaded = load_env(tmp_path)  # no .env present
    assert loaded == []


def test_malformed_line_is_skipped(tmp_path: Path, clean_env):
    env_file = tmp_path / ".env"
    env_file.write_text("this is garbage\nANTHROPIC_API_KEY=sk-ok\n")
    load_env(tmp_path)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ok"


def test_wiki_init_loads_env(tmp_path: Path, clean_env):
    """End-to-end: Wiki() should pick up a .env at its root."""
    from ringwood import Wiki

    env_file = tmp_path / ".env"
    env_file.write_text("WIKI_TEST_VAR=from-wiki-init\n")
    Wiki(root=tmp_path)
    assert os.environ["WIKI_TEST_VAR"] == "from-wiki-init"


def test_wiki_can_disable_dotenv(tmp_path: Path, clean_env):
    """If caller passes load_dotenv=False, we must NOT touch os.environ."""
    from ringwood import Wiki

    env_file = tmp_path / ".env"
    env_file.write_text("WIKI_TEST_VAR=should-not-load\n")
    Wiki(root=tmp_path, load_dotenv=False)
    assert "WIKI_TEST_VAR" not in os.environ
