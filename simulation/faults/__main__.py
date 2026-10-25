"""CLI: activate / reset / status for sim fault injectors (E5)."""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from faults.catalog import CATALOG, activation_plan


def _service_url(service: str) -> str:
    from common.faults import control_base_url

    return control_base_url(service)


def cmd_list() -> int:
    print(json.dumps({"injectors": sorted(CATALOG.keys())}, indent=2))
    return 0


def cmd_status() -> int:
    out: dict[str, object] = {}
    with httpx.Client(timeout=5.0) as client:
        for service in sorted({s["service"] for steps in CATALOG.values() for s in steps}):
            url = f"{_service_url(service).rstrip('/')}/v1/injectors"
            try:
                res = client.get(url)
                res.raise_for_status()
                out[service] = res.json()
            except httpx.HTTPError as exc:
                out[service] = {"error": str(exc)}
    print(json.dumps(out, indent=2))
    return 0


def cmd_activate(injector_id: str) -> int:
    plan = activation_plan(injector_id)
    results = []
    with httpx.Client(timeout=5.0) as client:
        for step in plan:
            service = step["service"]
            url = f"{_service_url(service).rstrip('/')}/v1/injectors/{injector_id}/activate"
            res = client.post(url, json={})
            res.raise_for_status()
            results.append(res.json())
    print(json.dumps({"injector": injector_id, "activated": results}, indent=2))
    print(f"ok activated {injector_id}", file=sys.stderr)
    return 0


def cmd_reset() -> int:
    targets = (
        "gateway",
        "auth",
        "checkout",
        "payment",
        "inventory",
        "notification",
    )
    results = []
    with httpx.Client(timeout=5.0) as client:
        for service in targets:
            url = f"{_service_url(service).rstrip('/')}/v1/injectors/reset"
            try:
                res = client.post(url)
                res.raise_for_status()
                results.append(res.json())
            except httpx.HTTPError as exc:
                results.append({"service": service, "error": str(exc)})
    print(json.dumps({"reset": results}, indent=2))
    print("ok reset injectors", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sim fault injectors (E5)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list injector ids")
    sub.add_parser("status", help="show active injectors per service")
    sub.add_parser("reset", help="clear injectors on all sim services")

    p_act = sub.add_parser("activate", help="activate an injector by id")
    p_act.add_argument(
        "injector",
        choices=sorted(CATALOG.keys()),
        help="scenario-class injector id",
    )

    args = parser.parse_args(argv)
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "reset":
        return cmd_reset()
    if args.cmd == "activate":
        return cmd_activate(args.injector)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
