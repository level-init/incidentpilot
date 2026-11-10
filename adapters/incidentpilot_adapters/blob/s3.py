"""S3/MinIO-compatible BlobStore (stdlib urllib + AWS SigV4)."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from incidentpilot_adapters.blob.protocol import BlobPutResult, BlobStoreError


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret).encode("utf-8"), datestamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


class S3BlobStore:
    """Path-style PutObject against MinIO or AWS S3."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket
        self.endpoint_url = (
            endpoint_url or os.environ.get("S3_ENDPOINT") or "https://s3.amazonaws.com"
        ).rstrip("/")
        self.region = region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self.access_key = (
            access_key
            or os.environ.get("AWS_ACCESS_KEY_ID")
            or os.environ.get("MINIO_ROOT_USER", "minioadmin")
        )
        self.secret_key = (
            secret_key
            or os.environ.get("AWS_SECRET_ACCESS_KEY")
            or os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
        )
        # Optional boto3-like double for tests that inject ``put_object``.
        self._client = client

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/json",
    ) -> BlobPutResult:
        digest = _sha256_hex(data)
        if self._client is not None:
            try:
                self._client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                    Metadata={"sha256": digest},
                )
            except Exception as exc:  # noqa: BLE001
                raise BlobStoreError(
                    f"s3 put failed for s3://{self.bucket}/{key}: {exc}"
                ) from exc
            return BlobPutResult(
                uri=f"s3://{self.bucket}/{key}",
                sha256=digest,
                byte_size=len(data),
            )

        try:
            self._put_sigv4(key, data, content_type=content_type, content_sha256=digest)
        except BlobStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BlobStoreError(
                f"s3 put failed for s3://{self.bucket}/{key}: {exc}"
            ) from exc
        return BlobPutResult(
            uri=f"s3://{self.bucket}/{key}",
            sha256=digest,
            byte_size=len(data),
        )

    def _put_sigv4(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        content_sha256: str,
    ) -> None:
        now = datetime.now(tz=UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        host = urlparse(self.endpoint_url).netloc
        # Path-style: /{bucket}/{key}
        canonical_uri = f"/{self.bucket}/{key.lstrip('/')}"
        payload_hash = content_sha256
        canonical_headers = (
            f"content-type:{content_type}\n"
            f"host:{host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            [
                "PUT",
                canonical_uri,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        credential_scope = f"{datestamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                _sha256_hex(canonical_request.encode("utf-8")),
            ]
        )
        signature = hmac.new(
            _signing_key(self.secret_key, datestamp, self.region, "s3"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        authorization = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        url = f"{self.endpoint_url}{canonical_uri}"
        req = Request(
            url,
            data=data,
            method="PUT",
            headers={
                "Content-Type": content_type,
                "Host": host,
                "x-amz-content-sha256": payload_hash,
                "x-amz-date": amz_date,
                "Authorization": authorization,
            },
        )
        try:
            with urlopen(req, timeout=30) as resp:  # noqa: S310 — configured S3/MinIO endpoint
                if resp.status not in (200, 201, 204):
                    raise BlobStoreError(
                        f"s3 put unexpected status {resp.status} for {url}"
                    )
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise BlobStoreError(f"HTTP {exc.code} putting {url}: {detail}") from exc
        except URLError as exc:
            raise BlobStoreError(f"request failed for {url}: {exc}") from exc


def build_evidence_blob_store() -> S3BlobStore:
    bucket = os.environ.get("S3_BUCKET_EVIDENCE", "incidentpilot-evidence")
    return S3BlobStore(bucket=bucket)


def resolve_evidence_blob_store() -> S3BlobStore | None:
    """Configured store, or ``None`` when object store is not set up.

    Presence of ``S3_ENDPOINT`` or ``AWS_ACCESS_KEY_ID`` enables uploads.
    Collectors treat ``None`` as STORE_UNAVAILABLE (MEDIUM RAW, no fake HIGH).
    """
    if not (os.environ.get("S3_ENDPOINT") or os.environ.get("AWS_ACCESS_KEY_ID")):
        return None
    return build_evidence_blob_store()


def build_ai_artifacts_blob_store() -> S3BlobStore:
    bucket = os.environ.get("S3_BUCKET_AI_ARTIFACTS", "incidentpilot-ai-artifacts")
    return S3BlobStore(bucket=bucket)


def resolve_ai_artifacts_blob_store() -> S3BlobStore | None:
    """AIInvocation artifact store (L3), or ``None`` when S3 is not configured."""
    if not (os.environ.get("S3_ENDPOINT") or os.environ.get("AWS_ACCESS_KEY_ID")):
        return None
    return build_ai_artifacts_blob_store()


def build_postmortem_export_blob_store() -> S3BlobStore:
    bucket = os.environ.get(
        "S3_BUCKET_POSTMORTEM_EXPORTS", "incidentpilot-postmortem-exports"
    )
    return S3BlobStore(bucket=bucket)


def resolve_postmortem_export_blob_store() -> S3BlobStore | None:
    """Postmortem export archive store (L6), or ``None`` when S3 is not configured."""
    if not (os.environ.get("S3_ENDPOINT") or os.environ.get("AWS_ACCESS_KEY_ID")):
        return None
    return build_postmortem_export_blob_store()
