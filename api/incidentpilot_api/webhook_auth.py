"""Alertmanager webhook authentication (F1).

AM does **not** use Slack HMAC. Supported local/demo mechanisms (any one match):

- ``Authorization: Bearer <token>`` vs ``ALERTMANAGER_WEBHOOK_TOKEN``
- HTTP Basic vs ``ALERTMANAGER_BASIC_USER`` / ``ALERTMANAGER_BASIC_PASSWORD``
- Custom header ``ALERTMANAGER_HEADER_NAME`` (default ``X-Alertmanager-Token``)
  vs ``ALERTMANAGER_HEADER_VALUE``
"""

from __future__ import annotations

import hmac
import os
import secrets
from base64 import b64decode

from fastapi import Header, HTTPException, Request, status


def _configured_bearer() -> str | None:
    tok = os.environ.get("ALERTMANAGER_WEBHOOK_TOKEN", "").strip()
    return tok or None


def _configured_basic() -> tuple[str, str] | None:
    user = os.environ.get("ALERTMANAGER_BASIC_USER", "").strip()
    password = os.environ.get("ALERTMANAGER_BASIC_PASSWORD", "").strip()
    if user and password:
        return user, password
    return None


def _configured_header() -> tuple[str, str] | None:
    name = os.environ.get("ALERTMANAGER_HEADER_NAME", "X-Alertmanager-Token").strip()
    value = os.environ.get("ALERTMANAGER_HEADER_VALUE", "").strip()
    if name and value:
        return name, value
    return None


def webhook_auth_configured() -> bool:
    return bool(_configured_bearer() or _configured_basic() or _configured_header())


def _const_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _check_bearer(authorization: str | None) -> bool:
    expected = _configured_bearer()
    if expected is None or not authorization:
        return False
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    return _const_eq(token.strip(), expected)


def _check_basic(authorization: str | None) -> bool:
    expected = _configured_basic()
    if expected is None or not authorization:
        return False
    scheme, _, blob = authorization.partition(" ")
    if scheme.lower() != "basic" or not blob:
        return False
    try:
        decoded = b64decode(blob.strip()).decode("utf-8")
    except Exception:
        return False
    user, sep, password = decoded.partition(":")
    if not sep:
        return False
    exp_user, exp_password = expected
    return _const_eq(user, exp_user) and _const_eq(password, exp_password)


def _check_custom_header(request: Request) -> bool:
    configured = _configured_header()
    if configured is None:
        return False
    name, expected = configured
    got = request.headers.get(name)
    if got is None:
        return False
    return _const_eq(got.strip(), expected)


async def require_alertmanager_auth(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """Reject unauthenticated Alertmanager webhook calls with 401."""
    if not webhook_auth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "alert webhook auth not configured; set ALERTMANAGER_WEBHOOK_TOKEN "
                "and/or BASIC_USER/PASSWORD and/or HEADER_VALUE"
            ),
        )
    if _check_bearer(authorization) or _check_basic(authorization) or _check_custom_header(request):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing alertmanager credentials",
        headers={"WWW-Authenticate": "Bearer, Basic"},
    )


def new_ingress_id() -> str:
    return secrets.token_hex(16)
