#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import time
from urllib.parse import urlparse

from openstack_auth import connect



def secret_id(value: str) -> str:
    path = urlparse(value).path if "://" in value else value
    return path.rstrip("/").split("/")[-1]


def create(args: argparse.Namespace) -> None:
    conn = connect(args.cloud, args.region)
    data = pathlib.Path(args.file).read_bytes()
    payload = base64.b64encode(data).decode("ascii")
    secret = conn.key_manager.create_secret(
        name=args.name,
        secret_type="opaque",
        payload=payload,
        payload_content_type=args.content_type,
        payload_content_encoding="base64",
    )
    sid = secret_id(secret.secret_ref)
    deadline = time.monotonic() + args.timeout
    final = secret
    while time.monotonic() < deadline:
        final = conn.key_manager.get_secret(sid)
        status = str(getattr(final, "status", "") or "").upper()
        if status == "ACTIVE":
            break
        if status in {"ERROR", "FAILED"}:
            raise SystemExit(f"Barbican secret {sid} entered {status}")
        time.sleep(1)
    else:
        raise SystemExit(f"timed out waiting for Barbican secret {sid} to become ACTIVE")
    print(json.dumps({
        "name": args.name,
        "secret_ref": final.secret_ref or secret.secret_ref,
        "secret_id": sid,
        "status": getattr(final, "status", None),
        "content_type": args.content_type,
    }))


def delete(args: argparse.Namespace) -> None:
    conn = connect(args.cloud, args.region)
    sid = secret_id(args.ref)
    conn.key_manager.delete_secret(sid, ignore_missing=True)
    print(json.dumps({"deleted": sid}))


def probe(args: argparse.Namespace) -> None:
    conn = connect(args.cloud, args.region)
    endpoint = conn.session.get_endpoint(
        service_type="key-manager",
        interface=args.interface,
        region_name=args.region or None,
    )
    if not endpoint:
        raise SystemExit("Barbican/key-manager endpoint was not found in the service catalog")
    print(json.dumps({"key_manager_endpoint": endpoint}))


def main() -> None:
    ap = argparse.ArgumentParser(description="Small openstacksdk Barbican helper")
    sub = ap.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cloud", required=True)
    common.add_argument("--region", default="")

    p = sub.add_parser("probe", parents=[common])
    p.add_argument("--interface", default="public")
    p.set_defaults(func=probe)

    p = sub.add_parser("create", parents=[common])
    p.add_argument("--name", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--content-type", default="application/octet-stream")
    p.add_argument("--timeout", type=int, default=60)
    p.set_defaults(func=create)

    p = sub.add_parser("delete", parents=[common])
    p.add_argument("--ref", required=True)
    p.set_defaults(func=delete)

    args = ap.parse_args()
    args.region = args.region or None
    args.func(args)


if __name__ == "__main__":
    main()
