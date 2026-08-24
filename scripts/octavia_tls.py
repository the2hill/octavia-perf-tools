#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time

import openstack


def connect(cloud: str, region: str | None):
    kwargs = {"cloud": cloud}
    if region:
        kwargs["region_name"] = region
    return openstack.connect(**kwargs)


def wait_pool(conn, pool_id: str, timeout: int) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pool = conn.load_balancer.get_pool(pool_id)
        status = getattr(pool, "provisioning_status", None)
        if status == "ACTIVE":
            return pool
        if status == "ERROR":
            raise SystemExit(f"pool {pool_id} entered ERROR")
        time.sleep(2)
    raise SystemExit(f"timed out waiting for pool {pool_id} to become ACTIVE")


def wait_listener(conn, listener_id: str, timeout: int) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        listener = conn.load_balancer.get_listener(listener_id)
        status = getattr(listener, "provisioning_status", None)
        if status == "ACTIVE":
            return listener
        if status == "ERROR":
            raise SystemExit(f"listener {listener_id} entered ERROR")
        time.sleep(2)
    raise SystemExit(f"timed out waiting for listener {listener_id} to become ACTIVE")


def parse_versions(value: str) -> list[str] | None:
    vals = [x.strip() for x in value.split(",") if x.strip()]
    return vals or None


def pool(args: argparse.Namespace) -> None:
    conn = connect(args.cloud, args.region)
    attrs = {"tls_enabled": True}
    if args.ca_ref:
        attrs["ca_tls_container_ref"] = args.ca_ref
    if args.tls_ref:
        attrs["tls_container_ref"] = args.tls_ref
    versions = parse_versions(args.tls_versions)
    if versions:
        attrs["tls_versions"] = versions
    if args.tls_ciphers:
        attrs["tls_ciphers"] = args.tls_ciphers
    updated = conn.load_balancer.update_pool(args.pool_id, **attrs)
    final = wait_pool(conn, args.pool_id, args.timeout)
    print(json.dumps({
        "id": final.id,
        "tls_enabled": getattr(final, "tls_enabled", None),
        "ca_tls_container_ref": getattr(final, "ca_tls_container_ref", None),
        "tls_versions": getattr(final, "tls_versions", None),
        "tls_ciphers": getattr(final, "tls_ciphers", None),
        "update_request_id": getattr(updated, "id", None),
    }))


def listener(args: argparse.Namespace) -> None:
    conn = connect(args.cloud, args.region)
    attrs = {}
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
        current = conn.load_balancer.get_listener(args.listener_id)
        print(json.dumps({"id": current.id, "updated": False}))
        return
    conn.load_balancer.update_listener(args.listener_id, **attrs)
    final = wait_listener(conn, args.listener_id, args.timeout)
    print(json.dumps({
        "id": final.id,
        "updated": True,
        "tls_versions": getattr(final, "tls_versions", None),
        "tls_ciphers": getattr(final, "tls_ciphers", None),
        "connection_limit": getattr(final, "connection_limit", None),
        "timeout_client_data": getattr(final, "timeout_client_data", None),
        "timeout_member_data": getattr(final, "timeout_member_data", None),
    }))


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply Octavia TLS attributes not exposed by the dedicated Ansible modules")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cloud", required=True)
    common.add_argument("--region", default="")
    common.add_argument("--timeout", type=int, default=600)
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

    args = ap.parse_args()
    args.region = args.region or None
    args.func(args)


if __name__ == "__main__":
    main()
