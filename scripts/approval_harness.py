#!/usr/bin/env python3
"""CLI: eval/test Approval harness (I6).

Emits a real ApprovalDecision via the API harness endpoint (not Slack).

Usage:
  export IP_API_URL=http://localhost:8000
  export IP_HARNESS_TOKEN=local-dev-evaluator
  python scripts/approval_harness.py approve <approval_id>
  python scripts/approval_harness.py reject <approval_id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _request(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise SystemExit(f"HTTP {exc.code}: {detail}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="I6 Approval harness CLI")
    parser.add_argument("action", choices=("approve", "reject"))
    parser.add_argument("approval_id", help="domain.approval id (UUID)")
    parser.add_argument(
        "--api",
        default=os.environ.get("IP_API_URL", "http://localhost:8000"),
        help="API base URL (default IP_API_URL or http://localhost:8000)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("IP_HARNESS_TOKEN", "local-dev-evaluator"),
        help="Bearer token with eval entitlement",
    )
    args = parser.parse_args()
    status = "APPROVED" if args.action == "approve" else "REJECTED"
    url = f"{args.api.rstrip('/')}/eval/approvals/{args.approval_id}/decide"
    result = _request("POST", url, args.token, {"status": status})
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
    sys.exit(0)
