"""Filesystem storage adapter — the default for personal/solo use.

Layout under `root`:
    wiki/
      entity/<slug>.md
      concept/<slug>.md
      decision/<slug>.md
      query/<slug>.md
      synthesis/<slug>.md
      index.md          (human-readable catalogue, maintained by engine)
      log.md            (append-only audit)
    .index/             (SQLite, etc. — managed by index adapters)
    raw/                (immutable sources — Karpathy layer 1)

Page ids are <kind>/<slug>. Slug is whatever the engine chose; we sanitize only
for filesystem safety.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Iterator

from .base import StorageAdapter, PageNotFound, StorageError


_SLUG_SAFE = re.compile(r"[^a-zA-Z0-9가-힣\-_.]")
_RESERVED = {"index", "log"}  # top-level names reserved for catalogue/audit


class LocalFSStorage(StorageAdapter):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.wiki_dir = self.root / "wiki"
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.wiki_dir / "log.md"

    # ── StorageAdapter ───────────────────────────────────────────────────

    def read(self, page_id: str) -> str:
        path = self._path(page_id)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise PageNotFound(page_id) from e

    def write(self, page_id: str, markdown: str) -> None:
        path = self._path(page_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, markdown)

    def exists(self, page_id: str) -> bool:
        return self._path(page_id).exists()

    def delete(self, page_id: str) -> None:
        try:
            self._path(page_id).unlink()
        except FileNotFoundError as e:
            raise PageNotFound(page_id) from e

    def list_ids(self, prefix: str | None = None) -> Iterator[str]:
        for md in sorted(self.wiki_dir.rglob("*.md")):
            rel = md.relative_to(self.wiki_dir)
            if rel.name in (f"{r}.md" for r in _RESERVED):
                continue
            page_id = rel.with_suffix("").as_posix()
            if prefix is None or page_id.startswith(prefix):
                yield page_id

    def read_log(self) -> str:
        if not self.log_path.exists():
            return ""
        return self.log_path.read_text(encoding="utf-8")

    def append_log(self, line: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            if not line.endswith("\n"):
                line += "\n"
            f.write(line)

    # ── Internals ────────────────────────────────────────────────────────

    def _path(self, page_id: str) -> Path:
        if not page_id or page_id.startswith("/") or ".." in page_id.split("/"):
            raise StorageError(f"invalid page id: {page_id!r}")
        parts = page_id.split("/")
        if parts[0] in _RESERVED:
            raise StorageError(f"page id collides with reserved name: {page_id!r}")
        safe = [_SLUG_SAFE.sub("_", p) for p in parts]
        return self.wiki_dir.joinpath(*safe).with_suffix(".md")


def _atomic_write(path: Path, content: str) -> None:
    """Write via tmp + os.replace so readers never see a half-written file."""
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".wiki-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
