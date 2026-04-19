"""Storage adapters — how pages are persisted.

Phase 0 ships LocalFS. Later adapters (MinIO for S3-compatible storage, Git for team sync)
implement the same protocol. The ringwood engine never calls storage directly
except through this interface.
"""

from .base import StorageAdapter, PageNotFound, StorageError
from .localfs import LocalFSStorage

__all__ = ["StorageAdapter", "LocalFSStorage", "PageNotFound", "StorageError"]
