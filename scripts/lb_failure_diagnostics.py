#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
from typing import Any

import openstack
import yaml


def connect(cloud: str, region: str | None):
    kwargs: dict[str, Any] = {"cloud": cloud}
    if region:
        kwargs["region_name"] = region
    return openstack.connect(**kwargs)


def as_dict(resource: Any) -> Any:
    if resource is None:
        return None
    if isinstance(resource, dict):
        return {str(k): as_dict(v) for k, v in resource.items()}
    if isinstance(resource, (list, tuple)):
        return [as_dict(v) for v in resource]
    if hasattr(resource, "to_dict"):
        try:
            return as_dict(resource.to_dict())
        except Exception:
            pass
    if isinstance(resource, (str, int, float, bool)):
        return resource
    return str(resource)


def record_error(data: dict[str, Any], key: str, exc: Exception) -> None:
    data.setdefault("errors", {})[key] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }


def status_tree(conn: Any, lb_id: str) -> Any:
    # openstacksdk does not expose this Octavia endpoint as a first-class helper.
    # The proxy session is a keystoneauth Adapter, so a service-relative path is
    # preferred and keeps catalog/interface/region selection intact.
    response = conn.load_balancer._session.get(  # noqa: SLF001 - intentional SDK adapter use
        f"/lbaas/loadbalancers/{lb_id}/status"
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Capture best-effort Octavia/Nova/Neutron state after a failed LB build"
    )
    ap.add_argument("--config", required=True)
    ap.add_argument("--load-balancer", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument(
        "--assert-absent",
        action="store_true",
        help="return non-zero when the named load balancer still exists",
    )
    args = ap.parse_args()

    cfg = yaml.safe_load(pathlib.Path(args.config).read_text()) or {}
    cloud_cfg = cfg.get("openstack") or {}
    cloud = str(cloud_cfg.get("cloud") or "")
    admin_cloud = str(cloud_cfg.get("admin_cloud") or "")
    region = str(cloud_cfg.get("region_name") or "") or None
    if not cloud:
        raise SystemExit("openstack.cloud is required in the benchmark config")
    if not admin_cloud:
        raise SystemExit(
            "openstack.admin_cloud is required for Amphora/Nova diagnostics"
        )

    out: dict[str, Any] = {
        "captured_at_utc": dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "cloud": cloud,
        "admin_cloud": admin_cloud,
        "region": region,
        "requested_load_balancer": args.load_balancer,
        "errors": {},
    }

    conn = connect(cloud, region)
    admin_conn = connect(admin_cloud, region)

    try:
        lb = conn.load_balancer.find_load_balancer(args.load_balancer, ignore_missing=True)
    except Exception as exc:
        record_error(out, "find_load_balancer", exc)
        lb = None

    if lb is None:
        out["load_balancer_found"] = False
    else:
        out["load_balancer_found"] = True
        try:
            lb = conn.load_balancer.get_load_balancer(lb.id)
        except Exception as exc:
            record_error(out, "get_load_balancer", exc)
        out["load_balancer"] = as_dict(lb)

        try:
            out["status_tree"] = status_tree(conn, lb.id)
        except Exception as exc:
            record_error(out, "status_tree", exc)

        try:
            listeners = list(conn.load_balancer.listeners(load_balancer_id=lb.id))
            out["listeners"] = [as_dict(x) for x in listeners]
        except Exception as exc:
            record_error(out, "listeners", exc)

        try:
            pools = list(conn.load_balancer.pools(load_balancer_id=lb.id))
            out["pools"] = [as_dict(x) for x in pools]
        except Exception as exc:
            record_error(out, "pools", exc)

        amphorae: list[Any] = []
        try:
            amphorae = list(admin_conn.load_balancer.amphorae(loadbalancer_id=lb.id))
            out["amphorae"] = [as_dict(x) for x in amphorae]
        except Exception as exc:
            record_error(out, "amphorae", exc)

        nova: list[dict[str, Any]] = []
        neutron_port_ids: set[str] = set()
        vip_port_id = getattr(lb, "vip_port_id", None)
        if vip_port_id:
            neutron_port_ids.add(str(vip_port_id))

        for amphora in amphorae:
            for attr in ("vrrp_port_id", "ha_port_id"):
                value = getattr(amphora, attr, None)
                if value:
                    neutron_port_ids.add(str(value))

            compute_id = getattr(amphora, "compute_id", None)
            if not compute_id:
                continue
            item: dict[str, Any] = {
                "amphora_id": getattr(amphora, "id", None),
                "compute_id": compute_id,
            }
            try:
                server = admin_conn.compute.get_server(compute_id)
                item["server"] = as_dict(server)
                try:
                    console = admin_conn.compute.get_server_console_output(server, length=120)
                    item["console_tail"] = as_dict(console)
                except Exception as exc:
                    item["console_error"] = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
            except Exception as exc:
                item["server_error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            nova.append(item)
        out["nova_amphora_servers"] = nova

        ports: list[dict[str, Any]] = []
        for port_id in sorted(neutron_port_ids):
            try:
                ports.append(as_dict(admin_conn.network.get_port(port_id)))
            except Exception as exc:
                ports.append(
                    {
                        "id": port_id,
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    }
                )
        out["neutron_ports"] = ports

    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, indent=2, sort_keys=True, default=str) + "\n")

    print(f"Wrote LB failure diagnostics: {output}")
    if lb is not None:
        print(
            "  LB: "
            f"id={getattr(lb, 'id', None)} "
            f"provisioning={getattr(lb, 'provisioning_status', None)} "
            f"operating={getattr(lb, 'operating_status', None)}"
        )
        for amphora in out.get("amphorae", []):
            print(
                "  Amphora: "
                f"id={amphora.get('id')} status={amphora.get('status')} "
                f"compute_id={amphora.get('compute_id')} zone={amphora.get('cached_zone')}"
            )
        for item in out.get("nova_amphora_servers", []):
            server = item.get("server") or {}
            if server:
                print(
                    "  Nova: "
                    f"id={item.get('compute_id')} status={server.get('status')} "
                    f"host={server.get('OS-EXT-SRV-ATTR:host') or server.get('compute_host')} "
                    f"fault={server.get('fault')}"
                )
    if out.get("errors"):
        print("  Diagnostics warnings:")
        for key, value in out["errors"].items():
            print(f"    {key}: {value['type']}: {value['message']}")
    if args.assert_absent and lb is not None:
        raise SystemExit(3)


if __name__ == "__main__":
    main()

