#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
from typing import Any

import yaml

from openstack_auth import cloud_label, connect


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
    """Return the Octavia status tree using a supported keystoneauth adapter.

    Newer openstacksdk Proxy objects no longer expose the private ``_session``
    attribute. CloudRegion.get_session_client() is the supported escape hatch for
    direct service-relative requests that are not wrapped by a high-level proxy.
    """
    adapter = conn.config.get_session_client("load-balancer")
    response = adapter.get(f"/lbaas/loadbalancers/{lb_id}/status")
    response.raise_for_status()
    return response.json()


def related_load_balancer_ids(resource: Any) -> set[str]:
    ids: set[str] = set()
    for attr in ("loadbalancer_id", "load_balancer_id"):
        value = getattr(resource, attr, None)
        if value:
            ids.add(str(value))

    for attr in ("loadbalancers", "load_balancers"):
        values = getattr(resource, attr, None) or []
        for item in values:
            if isinstance(item, dict):
                value = item.get("id")
            else:
                value = getattr(item, "id", None)
            if value:
                ids.add(str(value))
    return ids


def belongs_to_load_balancer(resource: Any, lb_id: str) -> bool:
    return str(lb_id) in related_load_balancer_ids(resource)


def collect_children(conn: Any, lb_id: str, out: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    """Collect only resources that actually belong to ``lb_id``.

    Some SDK/resource versions silently ignore an unknown list filter. Filtering
    the returned resources locally avoids diagnostics accidentally including
    pools/listeners from unrelated load balancers in the same project.
    """
    listeners: list[Any] = []
    pools: list[Any] = []

    try:
        listeners = [
            item
            for item in conn.load_balancer.listeners()
            if belongs_to_load_balancer(item, lb_id)
        ]
        out["listeners"] = [as_dict(item) for item in listeners]
    except Exception as exc:
        record_error(out, "listeners", exc)

    try:
        pools = [
            item
            for item in conn.load_balancer.pools()
            if belongs_to_load_balancer(item, lb_id)
        ]
        out["pools"] = [as_dict(item) for item in pools]
    except Exception as exc:
        record_error(out, "pools", exc)

    members: dict[str, list[Any]] = {}
    health_monitors: dict[str, Any] = {}
    for pool in pools:
        pool_id = str(getattr(pool, "id", ""))
        if not pool_id:
            continue
        try:
            members[pool_id] = [
                as_dict(item) for item in conn.load_balancer.members(pool_id)
            ]
        except Exception as exc:
            record_error(out, f"members:{pool_id}", exc)

        hm_id = getattr(pool, "health_monitor_id", None)
        if hm_id:
            try:
                health_monitors[pool_id] = as_dict(
                    conn.load_balancer.get_health_monitor(hm_id)
                )
            except Exception as exc:
                record_error(out, f"health_monitor:{pool_id}", exc)

    out["members_by_pool"] = members
    out["health_monitors_by_pool"] = health_monitors
    return listeners, pools


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Capture best-effort Octavia state and optional operator diagnostics "
            "after a failed LB build or scenario mutation"
        )
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
    cloud = cloud_cfg.get("cloud")
    admin_cloud = cloud_cfg.get("admin_cloud")
    region = str(cloud_cfg.get("region_name") or "") or None
    if not cloud:
        raise SystemExit("openstack.cloud is required in the benchmark config")

    out: dict[str, Any] = {
        "captured_at_utc": dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "cloud": cloud_label(cloud, "inline-tenant"),
        "admin_cloud": cloud_label(admin_cloud, "inline-admin") if admin_cloud else None,
        "region": region,
        "requested_load_balancer": args.load_balancer,
        "operator_diagnostics": {
            "status": "pending" if admin_cloud else "skipped",
            "reason": None if admin_cloud else "openstack.admin_cloud is not configured",
        },
        "errors": {},
    }

    try:
        tenant_conn = connect(cloud, region)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    try:
        lb = tenant_conn.load_balancer.find_load_balancer(
            args.load_balancer, ignore_missing=True
        )
    except Exception as exc:
        record_error(out, "find_load_balancer", exc)
        lb = None

    if lb is None:
        out["load_balancer_found"] = False
    else:
        out["load_balancer_found"] = True
        try:
            lb = tenant_conn.load_balancer.get_load_balancer(lb.id)
        except Exception as exc:
            record_error(out, "get_load_balancer", exc)
        out["load_balancer"] = as_dict(lb)

        try:
            out["status_tree"] = status_tree(tenant_conn, str(lb.id))
        except Exception as exc:
            record_error(out, "status_tree", exc)

        collect_children(tenant_conn, str(lb.id), out)

        if admin_cloud:
            try:
                admin_conn = connect(admin_cloud, region)
                out["operator_diagnostics"] = {"status": "enabled", "reason": None}
            except Exception as exc:
                admin_conn = None
                out["operator_diagnostics"] = {
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
                record_error(out, "admin_connect", exc)

            if admin_conn is not None:
                amphorae: list[Any] = []
                try:
                    amphorae = list(
                        admin_conn.load_balancer.amphorae(loadbalancer_id=lb.id)
                    )
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
                            console = admin_conn.compute.get_server_console_output(
                                server, length=120
                            )
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
        print(
            "  Scoped children: "
            f"listeners={len(out.get('listeners') or [])} "
            f"pools={len(out.get('pools') or [])}"
        )
        for amphora in out.get("amphorae", []):
            print(
                "  Amphora: "
                f"id={amphora.get('id')} status={amphora.get('status')} "
                f"compute_id={amphora.get('compute_id')} zone={amphora.get('cached_zone')}"
            )
    if out.get("operator_diagnostics", {}).get("status") == "skipped":
        print("  Operator diagnostics skipped: openstack.admin_cloud is not configured")
    if out.get("errors"):
        print("  Diagnostics warnings:")
        for key, value in out["errors"].items():
            print(f"    {key}: {value['type']}: {value['message']}")
    if args.assert_absent and lb is not None:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
