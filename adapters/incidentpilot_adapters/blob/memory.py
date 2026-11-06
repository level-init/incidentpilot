"""In-memory / failing BlobStore doubles for tests and fault injection."""

from __future__ import annotations

import hashlib

from incidentpilot_adapters.blob.protocol import BlobPutResult, BlobStoreError


class MemoryBlobStore:
    """Successful put — stores bytes keyed by URI."""

    def __init__(self, *, bucket: str = "incidentpilot-evidence") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/json",
    ) -> BlobPutResult:
        _ = content_type
        digest = hashlib.sha256(data).hexdigest()
        uri = f"s3://{self.bucket}/{key}"
        self.objects[uri] = data
        return BlobPutResult(uri=uri, sha256=digest, byte_size=len(data))


class FailingBlobStore:
    """Always raises — models MinIO/S3 down for G5 fallback tests."""

    def __init__(self, message: str = "object store unavailable") -> None:
        self.message = message

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/json",
    ) -> BlobPutResult:
        _ = (key, data, content_type)
        raise BlobStoreError(self.message)
