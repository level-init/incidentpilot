"""BlobStore protocol for evidence raw uploads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BlobStoreError(RuntimeError):
    """Raised when object store put/get fails."""


@dataclass(frozen=True, slots=True)
class BlobPutResult:
    uri: str
    sha256: str
    byte_size: int


class BlobStore(Protocol):
    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/json",
    ) -> BlobPutResult:
        """Upload bytes; return content-addressed URI + hash."""
        ...
