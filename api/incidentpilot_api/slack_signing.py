"""Slack request signature verification (K2) — api-only ``SLACK_SIGNING_SECRET``.

Spec: https://api.slack.com/authentication/verifying-requests-from-slack
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Final

from fastapi import HTTPException, Request, status

# Reject requests older/newer than this (Slack recommends 5 minutes).
SLACK_MAX_SKEW_SECONDS: Final[int] = 60 * 5


@dataclass(frozen=True, slots=True)
class VerifiedSlackBody:
    raw: bytes
    timestamp: int


def slack_signing_secret() -> str | None:
    secret = os.environ.get("SLACK_SIGNING_SECRET", "").strip()
    return secret or None


def compute_slack_signature(*, secret: str, timestamp: str, raw_body: bytes) -> str:
    base = f"v0:{timestamp}:".encode() + raw_body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def verify_slack_request(
    *,
    secret: str,
    timestamp: str | None,
    signature: str | None,
    raw_body: bytes,
    now: float | None = None,
) -> int:
    """Validate HMAC; return parsed timestamp. Raise ``HTTPException`` 401 on failure."""
    if not timestamp or not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Slack signature headers",
        )
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid Slack request timestamp",
        ) from exc

    clock = time.time() if now is None else now
    if abs(clock - ts) > SLACK_MAX_SKEW_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Slack request timestamp outside allowed skew",
        )

    expected = compute_slack_signature(
        secret=secret, timestamp=timestamp, raw_body=raw_body
    )
    if not hmac.compare_digest(expected, signature.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid Slack signature",
        )
    return ts


async def require_slack_signature(request: Request) -> VerifiedSlackBody:
    """FastAPI dependency: verify HMAC and return raw body + timestamp."""
    secret = slack_signing_secret()
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SLACK_SIGNING_SECRET not configured (api-only)",
        )
    raw = await request.body()
    ts = verify_slack_request(
        secret=secret,
        timestamp=request.headers.get("X-Slack-Request-Timestamp"),
        signature=request.headers.get("X-Slack-Signature"),
        raw_body=raw,
    )
    return VerifiedSlackBody(raw=raw, timestamp=ts)
