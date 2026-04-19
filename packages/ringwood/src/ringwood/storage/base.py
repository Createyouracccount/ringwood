"""Storage adapter contract.

Design constraints (PLAN.md §2):
  - Page id is a slash-separated path-like string, e.g. "concept/prompt-caching".
    Adapters are free to map this to filesystem paths, object-store keys, or
    git blobs — they just have to round-trip.
  - Adapters MUST be safe under concurrent reads. Writes are serialized by the
    caller (ringwood engine).
  - Adapters MUST NOT parse markdown. Pass strings verbatim.
"""

from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable


class StorageError(Exception):
    """Base class for storage-adapter failures."""


class PageNotFound(StorageError):
    """Raised when a read targets a page id that does not exist."""


@runtime_checkable
class StorageAdapter(Protocol):
    """Minimum surface a storage backend must provide.

    All methods are synchronous — Phase 0 adapters (LocalFS) are fast enough.
    An AsyncStorageAdapter variant can be added if/when we ship network backends
    (HTTP git, S3) that benefit from concurrency.
    """

    def read(self, page_id: str) -> str:
        """Return the raw markdown of `page_id` or raise PageNotFound."""
        ...

    def write(self, page_id: str, markdown: str) -> None:
        """Create or replace `page_id`. Must be atomic (write to tmp + rename)."""
        ...

    def exists(self, page_id: str) -> bool:
        ...

    def delete(self, page_id: str) -> None:
        """Hard delete. Engine avoids calling this — it invalidates instead.
        Kept for lint GC and tests."""
        ...

    def list_ids(self, prefix: str | None = None) -> Iterator[str]:
        """Yield page ids, optionally restricted to those starting with `prefix`."""
        ...

    def read_log(self) -> str:
        """Return the audit log (log.md) content. Empty string if absent."""
        ...

    def append_log(self, line: str) -> None:
        """Append a line to the audit log. Adapter handles newline."""
        ...
