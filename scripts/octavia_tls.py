#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Callable

from openstack_auth import connect


RETRYABLE_HTTP_STATUS = {409, 429, 500, 502, 503, 504}


def exception_status(exc: Exception) -> int | None:
    for attr in ("status_code", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def parent_load_balancer_id(resource: Any) -> str | None:
    for attr in ("loadbalancer_id", "load_balancer_id"):
        value = getattr(resource, attr, None)
        if value:
            return str(value)

    for attr in ("loadbalancers", "load_balancers"):
        values = getattr(resource, attr, None) or []
        for item in values:
            if isinstance(item, dict):
                value = item.get("id")
            else:
                value = getattr(item, "id", None)
            if value:
                return str(value)
    return None


def wait_load_balancer(conn: Any, load_balancer_id: str, timeout: int) -> Any:
    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        lb = conn.load_balancer.get_load_balancer(load_balancer_id)
        status = getattr(lb, "provisioning_status", None)
        last_status = status
        if status == "ACTIVE":
            return lb
        if status == "ERROR":
            raise RuntimeError(f"load balancer {load_balancer_id} entered ERROR")
        time.sleep(2)
    raise TimeoutError(
        f"timed out waiting for load balancer {load_balancer_id} to become ACTIVE; "
        f"last provisioning status={last_status}"
    )


def wait_pool(conn: Any, pool_id: str, timeout: int) -> Any:
    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        pool = conn.load_balancer.get_pool(pool_id)
        status = getattr(pool, "provisioning_status", None)
        last_status = status
        if status == "ACTIVE":
            return pool
        if status == "ERROR":
            raise RuntimeError(f"pool {pool_id} entered ERROR")
        time.sleep(2)
    raise TimeoutError(
        f"timed out waiting for pool {pool_id} to become ACTIVE; "
        f"last provisioning status={last_status}"
    )


def wait_listener(conn: Any, listener_id: str, timeout: int) -> Any:
    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        listener = conn.load_balancer.get_listener(listener_id)
        status = getattr(listener, "provisioning_status", None)
        last_status = status
        if status == "ACTIVE":
            return listener
        if status == "ERROR":
            raise RuntimeError(f"listener {listener_id} entered ERROR")
        time.sleep(2)
    raise TimeoutError(
        f"timed out waiting for listener {listener_id} to become ACTIVE; "
        f"last provisioning status={last_status}"
    )


def parse_versions(value: str) -> list[str] | None:
    vals = [x.strip() for x in value.split(",") if x.strip()]
    return vals or None


def update_with_retry(
    *,
    label: str,
    update: Callable[[], Any],
    wait_parent: Callable[[], Any] | None,
    wait_child: Callable[[], Any],
    retries: int,
    retry_delay: float,
) -> tuple[Any, Any]:
    attempts = max(1, retries)
    for attempt in range(1, attempts + 1):
        try:
            if wait_parent is not None:
                wait_parent()
            updated = update()
            final = wait_child()
            if wait_parent is not None:
                wait_parent()
            return updated, final
        except Exception as exc:
            status = exception_status(exc)
            retryable = status in RETRYABLE_HTTP_STATUS
            if not retryable or attempt >= attempts:
                raise
            print(
                f"{label} attempt {attempt}/{attempts} hit transient HTTP {status}; "
                f"retrying in {retry_delay:g}s: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(max(0.0, retry_delay))
    raise RuntimeError(f"{label} update exhausted retries")


def pool(args: argparse.Namespace) -> None:
    conn = connect(args.cloud, args.region)
    current = wait_pool(conn, args.pool_id, args.timeout)
    lb_id = parent_load_balancer_id(current)

    attrs: dict[str, Any] = {"tls_enabled": True}
    if args.ca_ref:
        attrs["ca_tls_container_ref"] = args.ca_ref
    if args.tls_ref:
        attrs["tls_container_ref"] = args.tls_ref
    versions = parse_versions(args.tls_versions)
    if versions:
        attrs["tls_versions"] = versions
    if args.tls_ciphers:
        attrs["tls_ciphers"] = args.tls_ciphers

    def wait_parent() -> Any:
        if not lb_id:
            return None
        return wait_load_balancer(conn, lb_id, args.timeout)

    updated, final = update_with_retry(
        label=f"pool {args.pool_id}",
        update=lambda: conn.load_balancer.update_pool(args.pool_id, **attrs),
        wait_parent=wait_parent if lb_id else None,
        wait_child=lambda: wait_pool(conn, args.pool_id, args.timeout),
        retries=args.retries,
        retry_delay=args.retry_delay,
    )

    if getattr(final, "tls_enabled", None) is not True:
        raise RuntimeError(
            f"pool {args.pool_id} update completed but tls_enabled is "
            f"{getattr(final, 'tls_enabled', None)!r}"
        )

    print(
        json.dumps(
            {
                "id": final.id,
                "load_balancer_id": lb_id,
                "tls_enabled": getattr(final, "tls_enabled", None),
                "ca_tls_container_ref": getattr(final, "ca_tls_container_ref", None),
                "tls_versions": getattr(final, "tls_versions", None),
                "tls_ciphers": getattr(final, "tls_ciphers", None),
                "update_request_id": getattr(updated, "id", None),
            }
        )
    )


def listener(args: argparse.Namespace) -> None:
    conn = connect(args.cloud, args.region)
    current = wait_listener(conn, args.listener_id, args.timeout)
    lb_id = parent_load_balancer_id(current)

    attrs: dict[str, Any] = {}
    versions = parse_versions(args.tls_versions)
    if versions:
        attrs["tls_versions"] = versions
    if args.tls_ciphers:
        attrs["tls_ciphers"] = args.tls_ciphers
    if args.connection_limit is not None:
        attrs["connection_limit"] = args.connection_limit
    if args.timeout_client_data is not None:
        attrs["timeout_client_data"] = args.timeout_client_data
    if args.timeout_member_data is not None:
        attrs["timeout_member_data"] = args.timeout_member_data

    if not attrs:
        print(json.dumps({"id": current.id, "updated": False, "load_balancer_id": lb_id}))
        return

    def wait_parent() -> Any:
        if not lb_id:
            return None
        return wait_load_balancer(conn, lb_id, args.timeout)

    _, final = update_with_retry(
        label=f"listener {args.listener_id}",
        update=lambda: conn.load_balancer.update_listener(args.listener_id, **attrs),
        wait_parent=wait_parent if lb_id else None,
        wait_child=lambda: wait_listener(conn, args.listener_id, args.timeout),
        retries=args.retries,
        retry_delay=args.retry_delay,
    )

    print(
        json.dumps(
            {
                "id": final.id,
                "load_balancer_id": lb_id,
                "updated": True,
                "tls_versions": getattr(final, "tls_versions", None),
                "tls_ciphers": getattr(final, "tls_ciphers", None),
                "connection_limit": getattr(final, "connection_limit", None),
                "timeout_client_data": getattr(final, "timeout_client_data", None),
                "timeout_member_data": getattr(final, "timeout_member_data", None),
            }
        )
    )


def wait_lb(args: argparse.Namespace) -> None:
    conn = connect(args.cloud, args.region)
    lb = wait_load_balancer(conn, args.load_balancer_id, args.timeout)
    print(
        json.dumps(
            {
                "id": lb.id,
                "provisioning_status": getattr(lb, "provisioning_status", None),
                "operating_status": getattr(lb, "operating_status", None),
            }
        )
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Apply Octavia TLS attributes and wait for safe mutation states"
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cloud", required=True)
    common.add_argument("--region", default="")
    common.add_argument("--timeout", type=int, default=600)
    common.add_argument("--retries", type=int, default=8)
    common.add_argument("--retry-delay", type=float, default=2.0)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pool", parents=[common])
    p.add_argument("--pool-id", required=True)
    p.add_argument("--ca-ref", default="")
    p.add_argument("--tls-ref", default="")
    p.add_argument("--tls-versions", default="")
    p.add_argument("--tls-ciphers", default="")
    p.set_defaults(func=pool)

    p = sub.add_parser("listener", parents=[common])
    p.add_argument("--listener-id", required=True)
    p.add_argument("--tls-versions", default="")
    p.add_argument("--tls-ciphers", default="")
    p.add_argument("--connection-limit", type=int)
    p.add_argument("--timeout-client-data", type=int)
    p.add_argument("--timeout-member-data", type=int)
    p.set_defaults(func=listener)

    p = sub.add_parser("wait-lb", parents=[common])
    p.add_argument("--load-balancer-id", required=True)
    p.set_defaults(func=wait_lb)

    args = ap.parse_args()
    if args.timeout <= 0:
        ap.error("--timeout must be > 0")
    if args.retries < 1:
        ap.error("--retries must be >= 1")
    if args.retry_delay < 0:
        ap.error("--retry-delay must be >= 0")
    args.region = args.region or None
    try:
        args.func(args)
    except Exception as exc:
        print(
            f"octavia_tls {args.command} failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
