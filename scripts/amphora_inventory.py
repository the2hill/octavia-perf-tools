#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import time
from typing import Any

import yaml

from openstack_auth import connect as openstack_connect


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text())
    return value if isinstance(value, dict) else {}


def write_yaml(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False))
    path.chmod(0o600)


def iso(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return str(value)


def attr(obj: Any, name: str, default: Any = None) -> Any:
    value = getattr(obj, name, default)
    return default if value is None else value


def connect_from_config(config_path: pathlib.Path):
    cfg = load_yaml(config_path)
    cloud_cfg = cfg.get("openstack") or {}
    admin_cloud = cloud_cfg.get("admin_cloud")
    if not admin_cloud:
        raise SystemExit(
            "openstack.admin_cloud is required for Amphora/Nova inventory capture"
        )
    region = cloud_cfg.get("region_name")
    try:
        return openstack_connect(admin_cloud, str(region) if region else None)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


def nova_details(conn: Any, compute_id: str) -> dict[str, Any]:
    server = conn.compute.get_server(compute_id)
    return {
        "compute_id": compute_id,
        "instance_name": attr(server, "instance_name"),
        "server_name": attr(server, "name"),
        "server_status": attr(server, "status"),
        "compute_host": attr(server, "compute_host") or attr(server, "host"),
        "hypervisor_hostname": attr(server, "hypervisor_hostname"),
        "availability_zone": attr(server, "availability_zone"),
        "nova_flavor_id": attr(server, "flavor_id"),
        "nova_image_id": attr(server, "image_id"),
        "server_created_at": iso(attr(server, "created_at")),
        "server_launched_at": iso(attr(server, "launched_at")),
    }


def amphora_record(conn: Any, amphora: Any) -> dict[str, Any]:
    compute_id = str(attr(amphora, "compute_id", "") or "")
    record: dict[str, Any] = {
        "amphora_id": str(attr(amphora, "id", "") or ""),
        "role": attr(amphora, "role"),
        "status": attr(amphora, "status"),
        "compute_id": compute_id or None,
        "lb_network_ip": attr(amphora, "lb_network_ip"),
        "vrrp_ip": attr(amphora, "vrrp_ip"),
        "ha_ip": attr(amphora, "ha_ip"),
        "vrrp_port_id": attr(amphora, "vrrp_port_id"),
        "ha_port_id": attr(amphora, "ha_port_id"),
        "cached_zone": attr(amphora, "cached_zone"),
        "amphora_image_id": attr(amphora, "image_id"),
        "amphora_compute_flavor_id": attr(amphora, "compute_flavor"),
        "created_at": iso(attr(amphora, "created_at")),
        "updated_at": iso(attr(amphora, "updated_at")),
    }
    if compute_id:
        record.update(nova_details(conn, compute_id))
    else:
        record.update(
            {
                "instance_name": None,
                "server_name": None,
                "server_status": None,
                "compute_host": None,
                "hypervisor_hostname": None,
                "availability_zone": None,
                "nova_flavor_id": None,
                "nova_image_id": None,
                "server_created_at": None,
                "server_launched_at": None,
            }
        )
    return record


def choose_primary(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    for preferred in ("STANDALONE", "MASTER"):
        for record in records:
            if str(record.get("role") or "").upper() == preferred:
                return record
    return records[0] if records else None


def update_registry(registry_path: pathlib.Path, state: dict[str, Any]) -> None:
    campaign_id = str(state.get("campaign_id") or "")
    flavor = str(state.get("octavia_flavor") or "")
    registry = load_yaml(registry_path)
    if str(registry.get("campaign_id") or "") != campaign_id:
        registry = {"schema_version": 1, "campaign_id": campaign_id, "load_balancers": []}

    load_balancers = [
        item
        for item in (registry.get("load_balancers") or [])
        if not (
            str(item.get("campaign_id") or "") == campaign_id
            and str(item.get("octavia_flavor") or "") == flavor
        )
    ]
    load_balancers.append(state)
    registry["load_balancers"] = load_balancers
    registry["updated_at_utc"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    write_yaml(registry_path, registry)


def remove_registry_entry(registry_path: pathlib.Path, campaign_id: str, flavor: str) -> None:
    registry = load_yaml(registry_path)
    if not registry:
        return
    remaining = [
        item
        for item in (registry.get("load_balancers") or [])
        if not (
            str(item.get("campaign_id") or "") == campaign_id
            and str(item.get("octavia_flavor") or "") == flavor
        )
    ]
    registry["load_balancers"] = remaining
    registry["updated_at_utc"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    write_yaml(registry_path, registry)


def capture(args: argparse.Namespace) -> None:
    state_path = pathlib.Path(args.state_file)
    state = load_yaml(state_path)
    if not state:
        raise SystemExit(f"campaign state file does not exist or is empty: {state_path}")

    lb_id = str(state.get("load_balancer_id") or args.load_balancer_id or "")
    if not lb_id:
        raise SystemExit("load_balancer_id is missing from campaign state")

    conn = connect_from_config(pathlib.Path(args.config))
    records: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for attempt in range(1, args.retries + 1):
        try:
            amphorae = list(conn.load_balancer.amphorae(loadbalancer_id=lb_id))
            records = [amphora_record(conn, amphora) for amphora in amphorae]
            if records and all(item.get("compute_id") and item.get("instance_name") for item in records):
                break
        except Exception as exc:  # capture is retried because Nova/Octavia data can lag LB ACTIVE briefly
            last_error = exc
            records = []
        if attempt < args.retries:
            time.sleep(args.delay_seconds)

    provider = str(state.get("provider") or "")
    if provider.lower() == "amphora" and not records:
        detail = f": {last_error}" if last_error else ""
        raise SystemExit(f"no Amphora inventory found for load balancer {lb_id}{detail}")
    if provider.lower() == "amphora" and any(not item.get("instance_name") for item in records):
        raise SystemExit(
            f"Amphora inventory for load balancer {lb_id} is missing Nova instance_name; "
            "the benchmark account may not have access to extended server attributes"
        )

    primary_record = choose_primary(records)
    primary = dict(primary_record) if primary_record else None
    domains = [str(item["instance_name"]) for item in records if item.get("instance_name")]
    captured = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    state.update(
        {
            "state_schema_version": 2,
            "amphora_inventory_captured_at_utc": captured,
            "amphora_count": len(records),
            "amphorae": records,
            "primary_amphora": primary,
            "prometheus_libvirt_domains": domains,
            "prometheus_libvirt_domain_regex": "|".join(domains) if domains else None,
        }
    )

    write_yaml(state_path, state)
    if args.registry_file:
        update_registry(pathlib.Path(args.registry_file), state)
    if args.archive_file:
        write_yaml(pathlib.Path(args.archive_file), state)

    print(json.dumps(state, indent=2, default=str))


def remove(args: argparse.Namespace) -> None:
    if args.registry_file:
        remove_registry_entry(
            pathlib.Path(args.registry_file),
            str(args.campaign_id),
            str(args.octavia_flavor),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture durable Octavia Amphora/Nova identity for benchmark runs")
    sub = parser.add_subparsers(dest="command", required=True)

    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("--config", required=True)
    capture_parser.add_argument("--state-file", required=True)
    capture_parser.add_argument("--load-balancer-id")
    capture_parser.add_argument("--registry-file")
    capture_parser.add_argument("--archive-file")
    capture_parser.add_argument("--retries", type=int, default=12)
    capture_parser.add_argument("--delay-seconds", type=float, default=5.0)
    capture_parser.set_defaults(func=capture)

    remove_parser = sub.add_parser("remove")
    remove_parser.add_argument("--registry-file", required=True)
    remove_parser.add_argument("--campaign-id", required=True)
    remove_parser.add_argument("--octavia-flavor", required=True)
    remove_parser.set_defaults(func=remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

