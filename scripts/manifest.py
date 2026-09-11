#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import yaml


def load_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    value = yaml.safe_load(path.read_text())
    return ({} if default is None else default) if value is None else value


def safe_openstack_metadata(value: Any) -> dict[str, Any]:
    src = value if isinstance(value, dict) else {}
    cloud = src.get("cloud")
    admin_cloud = src.get("admin_cloud")
    return {
        "cloud": cloud if isinstance(cloud, str) else "inline-tenant",
        "admin_cloud": admin_cloud if isinstance(admin_cloud, str) else "inline-admin",
        "region_name": src.get("region_name"),
        "environment_label": src.get("environment_label"),
        "validate_certs": src.get("validate_certs"),
    }


def compact_flavor(value: Any, fallback_name: str | None = None) -> dict[str, Any]:
    src = value if isinstance(value, dict) else {}
    return {
        "name": src.get("name") or fallback_name,
        "id": src.get("id"),
        "vcpus": src.get("vcpus"),
        "ram_mb": src.get("ram"),
        "disk_gb": src.get("disk"),
        "ephemeral_gb": src.get("ephemeral"),
        "swap_mb": src.get("swap"),
        "rxtx_factor": src.get("rxtx_factor"),
        "extra_specs": src.get("extra_specs") or {},
    }


def compact_image(value: Any, requested: str | None = None) -> dict[str, Any]:
    src = value if isinstance(value, dict) else {}
    return {
        "requested": requested,
        "name": src.get("name"),
        "id": src.get("id"),
        "checksum": src.get("checksum"),
        "hash_algo": src.get("hash_algo"),
        "hash_value": src.get("hash_value"),
        "created_at": src.get("created_at"),
        "updated_at": src.get("updated_at"),
        "size_bytes": src.get("size"),
        "disk_format": src.get("disk_format"),
        "architecture": src.get("architecture"),
        "os_distro": src.get("os_distro"),
        "os_version": src.get("os_version"),
    }


def git_metadata(repo_root: Path) -> dict[str, Any]:
    def cmd(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=repo_root, text=True, capture_output=True, check=True
            ).stdout.strip()
            return out or None
        except (OSError, subprocess.CalledProcessError):
            return None

    commit = cmd("rev-parse", "HEAD")
    status = cmd("status", "--porcelain") if commit else None
    return {"git_commit": commit, "git_dirty": bool(status) if commit else None}


def harness_hash(repo_root: Path) -> str:
    files = [
        "config/example.yml",
        "roles/locust/files/locustfile.py",
        "roles/locust/files/connection_capacity.py",
        "roles/backend/templates/nginx.conf.j2",
        "roles/backend/tasks/main.yml",
        "roles/common/tasks/main.yml",
        "playbooks/run_test.yml",
        "playbooks/create_lb.yml",
        "playbooks/create_campaign_lb.yml",
        "playbooks/configure_campaign_lb_scenario.yml",
        "playbooks/prepare_tls.yml",
        "scripts/benchmark.py",
        "scripts/amphora_inventory.py",
        "scripts/grafana_prometheus_diagnostics.py",
        "scripts/topology.py",
        "scripts/controller_fip_route.py",
        "playbooks/provision.yml",
        "templates/inventory.ini.j2",
        "scripts/tls_material.py",
        "scripts/barbican_secret.py",
        "scripts/octavia_tls.py",
        "requirements.txt",
    ]
    digest = hashlib.sha256()
    for rel in files:
        path = repo_root / rel
        digest.update(rel.encode() + b"\0")
        if path.exists():
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def grouped_node_fingerprint(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for node in nodes:
        normalized.append(
            {
                "roles": sorted(node.get("roles") or []),
                "os": node.get("os") or {},
                "cpu": node.get("cpu") or {},
                "memory": node.get("memory") or {},
                "network": {
                    "mtu": (node.get("network") or {}).get("mtu"),
                    "interface": (node.get("network") or {}).get("interface"),
                },
                "software": node.get("software") or {},
                "kernel_settings": node.get("kernel_settings") or {},
            }
        )
    return sorted(normalized, key=lambda x: json.dumps(x, sort_keys=True, default=str))


def fingerprint(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def fmt_flavor(flavor: dict[str, Any]) -> str:
    name = flavor.get("name") or "unknown"
    parts = []
    if flavor.get("vcpus") is not None:
        parts.append(f"{flavor['vcpus']} vCPU")
    if flavor.get("ram_mb") is not None:
        parts.append(f"{float(flavor['ram_mb']) / 1024:g} GiB RAM")
    if flavor.get("disk_gb") is not None:
        parts.append(f"{flavor['disk_gb']} GiB disk")
    return f"{name} ({', '.join(parts)})" if parts else str(name)


def safe(value: Any, fallback: str = "n/a") -> str:
    return fallback if value in (None, "") else str(value)


def payload_bytes(path: str | None) -> int | None:
    if not path:
        return None
    leaf = str(path).rsplit("/", 1)[-1]
    if leaf.endswith(".bin") and leaf[:-4].isdigit():
        return int(leaf[:-4])
    return None


def manifest_markdown(manifest: dict[str, Any]) -> str:
    gen = manifest["load_generator"]
    backend = manifest["backend"]
    target = manifest["target"]
    cloud = manifest["cloud"]
    image = manifest["vm_image"]
    workload = manifest["workload"]
    octavia = manifest["octavia"]
    scenario = manifest["scenario"]
    generator_network = manifest.get("generator_network") or {}
    nodes = manifest.get("nodes") or []

    rows = [
        ("Benchmark ID", manifest["benchmark_id"]),
        ("Suite ID", safe((manifest.get("target") or {}).get("suite_id") or (manifest.get("target") or {}).get("campaign_id"))),
        ("Direct control for flavor", safe((manifest.get("target") or {}).get("baseline_for_flavor"))),
        ("Captured (UTC)", manifest["captured_at_utc"]),
        ("Load window (UTC)", f"{safe((manifest.get('timing') or {}).get('load_test_started_at_utc'))} -> {safe((manifest.get('timing') or {}).get('load_test_completed_at_utc'))}"),
        ("Comparison fingerprint", manifest["comparison_fingerprint"]),
        ("Scenario", f"{scenario.get('name')} - {safe(scenario.get('description'))}"),
        ("Traffic path", scenario.get("traffic_path")),
        ("External network MTU", safe((manifest.get("network") or {}).get("external_network_mtu"))),
        ("Controller FIP route", f"managed={safe((manifest.get('network') or {}).get('controller_fip_route_managed'))}, mtu={safe((manifest.get('network') or {}).get('controller_fip_route_mtu'))}"),
        ("Generator network", f"{safe(generator_network.get('resolved_mode'))} / {safe(generator_network.get('network_name'))} / {safe(generator_network.get('cidr'))}"),
        ("Generator/backend isolation", safe(generator_network.get("isolated_from_backends"))),
        ("Direct backend reachable", safe(generator_network.get("direct_backend_reachable"))),
        ("Target", f"{target.get('target_kind')} / {target.get('octavia_flavor')} / provider {safe(target.get('provider'))}"),
        ("TLS datapath", f"frontend termination={scenario.get('frontend_tls_termination')}, backend TLS={scenario.get('backend_tls')}, re-encryption={scenario.get('backend_reencrypt')}"),
        ("Benchmark engine", scenario.get("benchmark_engine")),
        ("Locust profile", safe(scenario.get("locust_profile"))),
        ("HTTP connection mode", scenario.get("connection_mode")),
        ("Connection capacity mode", safe(scenario.get("capacity_mode"))),
        ("Connection capacity profile", safe(scenario.get("capacity_profile"))),
        ("Payload", f"{scenario.get('benchmark_path')} ({safe(scenario.get('payload_bytes'))} bytes)"),
        ("Campaign", safe((manifest.get("metadata") or {}).get("campaign_label"))),
        ("Cloud", f"{safe(cloud.get('cloud'))} / region {safe(cloud.get('region_name'))}"),
        ("Environment", safe(cloud.get("environment_label"))),
        ("VM image", f"{safe(image.get('name') or image.get('requested'))} [{safe(image.get('id'))}]"),
        ("Locust master", fmt_flavor(gen["master"]["flavor"])),
        ("Generator VMs", (
            f"{gen['workers']['count']} VMs x {fmt_flavor(gen['workers']['flavor'])}; "
            + (
                f"{workload.get('processes_per_vm')} capacity processes/VM = {gen['workers']['count'] * int(workload.get('processes_per_vm') or 0)} capacity processes"
                if workload.get("engine") == "connection_capacity"
                else f"{gen['workers']['processes_per_vm']} Locust processes/VM = {gen['workers']['total_processes']} Locust worker processes"
            )
        )),
        ("Backend members", f"{backend['count']} VMs x {fmt_flavor(backend['flavor'])}; native nginx"),
        ("Listener/pool", f"{octavia.get('listener_protocol')}:{octavia.get('listener_port')} -> {octavia.get('pool_protocol')}:{octavia.get('member_port')} / {octavia.get('lb_algorithm')}"),
        ("Listener policy", f"connection_limit={safe(octavia.get('listener_connection_limit'))}, client_timeout={safe(octavia.get('listener_timeout_client_data_ms'))}ms, member_timeout={safe(octavia.get('listener_timeout_member_data_ms'))}ms"),
        ("Workload", (
            f"connection targets={workload.get('levels')}, ramp={workload.get('ramp_seconds')}s, hold={workload.get('hold_seconds')}s"
            if workload.get("engine") == "connection_capacity"
            else (
                f"adaptive max-RPS search {safe(workload.get('max_rps'))}"
                if workload.get("locust_profile") == "max_rps"
                else f"{len(workload.get('stages') or [])} stages, {workload.get('total_duration_seconds')}s total, timeout {workload.get('request_timeout_seconds')}s"
            )
        )),
    ]

    lines = [f"# Run manifest: {manifest['benchmark_id']}", "", "## Comparison-critical specification", ""]
    lines += [f"- **{label}:** {value}" for label, value in rows]
    if workload.get("engine") == "connection_capacity":
        lines += ["", "## Connection-capacity workload", ""]
        lines.append(f"- **Global connection targets:** {workload.get('levels')}")
        lines.append(f"- **Capacity mode:** {safe(workload.get('capacity_mode'))}")
        lines.append(f"- **Processes per generator VM:** {safe(workload.get('processes_per_vm'))}")
        lines.append(f"- **Ramp / hold / heartbeat:** {safe(workload.get('ramp_seconds'))}s / {safe(workload.get('hold_seconds'))}s / {safe(workload.get('heartbeat_seconds'))}s")
        lines.append(f"- **Failure threshold:** {safe(workload.get('failure_threshold_percent'))}%")
        lines.append(f"- **Source-port guard per generator VM:** {safe(workload.get('source_port_guard_per_worker'))}")
        lines.append(f"- **File descriptor limit:** {safe(workload.get('file_descriptor_limit'))}")
    elif workload.get("locust_profile") == "max_rps":
        lines += ["", "## Adaptive max-RPS workload", ""]
        for key, value in (workload.get("max_rps") or {}).items():
            lines.append(f"- **{key}:** {safe(value)}")
    else:
        lines += ["", "## Load stages", "", "| Users | Duration (s) | Spawn rate |", "|---:|---:|---:|"]
        for stage in workload.get("stages") or []:
            lines.append(f"| {stage.get('users')} | {stage.get('duration_seconds')} | {stage.get('spawn_rate')} |")

    lines += ["", "## TLS and Octavia target", ""]
    for label, value in [
        ("Load balancer name", target.get("load_balancer_name")),
        ("Load balancer ID", target.get("load_balancer_id")),
        ("Listener ID", target.get("listener_id")),
        ("Pool ID", target.get("pool_id")),
        ("Provider", target.get("provider")),
        ("Flavor ID", target.get("flavor_id")),
        ("Amphora count", target.get("amphora_count")),
        ("Primary Amphora ID", target.get("amphora_id")),
        ("Primary Amphora role", target.get("amphora_role")),
        ("Primary Amphora compute ID", target.get("amphora_compute_id")),
        ("Primary libvirt domain", target.get("amphora_instance_name")),
        ("Primary compute host", target.get("amphora_compute_host")),
        ("Primary hypervisor hostname", target.get("amphora_hypervisor_hostname")),
        ("Prometheus libvirt domain regex", target.get("prometheus_libvirt_domain_regex")),
        ("VIP", target.get("vip_address")),
        ("Target host", target.get("target_host")),
        ("Target URL", target.get("target_url")),
        ("Barbican frontend secret used", bool(target.get("listener_tls_secret_ref"))),
        ("Barbican backend CA secret used", bool(target.get("backend_ca_secret_ref"))),
    ]:
        lines.append(f"- **{label}:** {safe(value)}")
    amphorae = target.get("amphorae") or []
    if amphorae:
        lines += ["", "## Amphora / Nova identity", "", "| Role | Amphora ID | Compute ID | Libvirt domain | Compute host | Hypervisor | Mgmt IP |", "|---|---|---|---|---|---|---|"]
        for amphora in amphorae:
            lines.append(
                "| "
                + " | ".join(
                    safe(amphora.get(key))
                    for key in [
                        "role",
                        "amphora_id",
                        "compute_id",
                        "instance_name",
                        "compute_host",
                        "hypervisor_hostname",
                        "lb_network_ip",
                    ]
                )
                + " |"
            )

    tls_cfg = manifest.get("tls") or {}
    lines.append(f"- **Configured frontend TLS versions:** {safe(tls_cfg.get('listener_tls_versions'))}")
    lines.append(f"- **Configured frontend TLS ciphers:** {safe(tls_cfg.get('listener_tls_ciphers'))}")
    lines.append(f"- **Configured backend TLS versions:** {safe(tls_cfg.get('pool_tls_versions'))}")
    lines.append(f"- **Configured backend TLS ciphers:** {safe(tls_cfg.get('pool_tls_ciphers'))}")

    placement = manifest.get("infrastructure") or {}
    lines += ["", "## OpenStack placement metadata", ""]
    for item in [placement.get("master_server")] + list(placement.get("locust_servers") or []) + list(placement.get("backend_servers") or []):
        if not item:
            continue
        lines.append(f"- **{safe(item.get('name'))}:** AZ={safe(item.get('availability_zone'))}, host={safe(item.get('host'))}, hypervisor={safe(item.get('hypervisor_hostname'))}")

    lines += ["", "## Node inventory", ""]
    lines += ["| Node | Roles | OS | Kernel | vCPU | RAM MiB | CPU model | Interface/MTU | Software |", "|---|---|---|---|---:|---:|---|---|---|"]
    for node in nodes:
        os_data = node.get("os") or {}
        cpu = node.get("cpu") or {}
        memory = node.get("memory") or {}
        net = node.get("network") or {}
        software = node.get("software") or {}
        software_text = "; ".join(f"{k}={v}" for k, v in software.items() if v not in (None, "")) or "n/a"
        lines.append(
            "| {node} | {roles} | {os} | {kernel} | {vcpus} | {ram} | {cpu_model} | {iface}/{mtu} | {software} |".format(
                node=safe(node.get("node")),
                roles=", ".join(node.get("roles") or []),
                os=f"{safe(os_data.get('distribution'))} {safe(os_data.get('version'))}",
                kernel=safe(os_data.get("kernel")),
                vcpus=safe(cpu.get("vcpus")),
                ram=safe(memory.get("total_mb")),
                cpu_model=safe(cpu.get("model")).replace("|", "/"),
                iface=safe(net.get("interface")),
                mtu=safe(net.get("mtu")),
                software=software_text.replace("|", "/"),
            )
        )

    lines += ["", "## Resolved flavor metadata", ""]
    for label, value in [("Master", gen["master"]["flavor"]), ("Locust worker", gen["workers"]["flavor"]), ("Backend", backend["flavor"])]:
        lines += [f"### {label}", "", "```yaml", yaml.safe_dump(value, sort_keys=True).strip(), "```", ""]

    metadata = manifest.get("metadata") or {}
    lines += ["## Campaign metadata", ""]
    lines.append(f"- **Campaign label:** {safe(metadata.get('campaign_label'))}")
    lines.append(f"- **Cloud build:** {safe(metadata.get('cloud_build'))}")
    lines.append(f"- **Notes:** {safe(metadata.get('notes'))}")

    tool = manifest.get("tool") or {}
    lines += ["", "## Tool provenance", ""]
    lines.append(f"- **Git commit:** {safe(tool.get('git_commit'))}")
    lines.append(f"- **Git dirty:** {safe(tool.get('git_dirty'))}")
    lines.append(f"- **Harness hash:** {safe(tool.get('harness_sha256'))}")
    lines += ["", "The comparison fingerprint intentionally excludes the Octavia flavor under test and ephemeral resource/secret IDs. Compatibility is evaluated within each scenario, traffic path, and generator topology, so HTTP/TLS profiles and materially different network origins remain separate comparison populations.", ""]
    return "\n".join(lines)


def build_manifest(result_dir: Path) -> dict[str, Any]:
    target = load_yaml(result_dir / "target.yml")
    cfg = load_yaml(result_dir / "config-effective.yml")
    infra = load_yaml(result_dir / "infrastructure.yml")
    network_manifest = dict(cfg.get("network") or {})
    network_manifest["external_network_mtu"] = infra.get("external_network_mtu")
    network_manifest["controller_fip_route_managed"] = bool(infra.get("controller_fip_route_managed", False))
    network_manifest["controller_fip_route_mtu"] = infra.get("controller_fip_route_mtu")
    timing = load_yaml(result_dir / "timing.yml")
    tls_material_path = result_dir / "tls-material.json"
    tls_material = json.loads(tls_material_path.read_text()) if tls_material_path.exists() else {}
    prometheus_diag_path = result_dir / "prometheus-diagnostics.json"
    if prometheus_diag_path.exists():
        try:
            prometheus_diag = json.loads(prometheus_diag_path.read_text())
        except (OSError, json.JSONDecodeError):
            prometheus_diag = {"status": "unreadable"}
    else:
        prometheus_diag = {"status": "missing"}
    nodes = []
    for path in sorted((result_dir / "node-specs").glob("*.yml")):
        value = load_yaml(path)
        if isinstance(value, dict):
            nodes.append(value)

    vm = cfg.get("vm") or {}
    locust = cfg.get("locust") or {}
    capacity_cfg = cfg.get("connection_capacity") or {}
    max_rps_cfg = cfg.get("max_rps") or {}
    generator_network_cfg = cfg.get("generator_network") or {"mode": "auto"}
    backend_cfg = cfg.get("backend") or {}
    octavia_cfg = cfg.get("octavia") or {}
    tls_cfg = cfg.get("tls") or {}
    stages = locust.get("stages") or []

    master_flavor = compact_flavor(infra.get("selected_master_flavor_info"), infra.get("selected_master_flavor"))
    worker_flavor = compact_flavor(infra.get("selected_locust_flavor_info"), infra.get("selected_locust_flavor"))
    backend_flavor = compact_flavor(infra.get("selected_backend_flavor_info"), infra.get("selected_backend_flavor"))
    image = compact_image(infra.get("image_info"), vm.get("image"))
    worker_count = int((vm.get("locust") or {}).get("worker_vms", 0))
    processes_per_vm = int((vm.get("locust") or {}).get("processes_per_vm", 0))

    repo_root = result_dir.resolve().parents[1]
    tool = git_metadata(repo_root)
    tool["harness_sha256"] = harness_hash(repo_root)

    capacity_profile = target.get("capacity_profile") or "standard"
    if capacity_profile == "max":
        effective_capacity_levels = [
            int(x) * worker_count for x in (capacity_cfg.get("max_levels_per_worker") or [])
        ]
    else:
        effective_capacity_levels = [int(x) for x in (capacity_cfg.get("levels") or [])]

    scenario = {
        "name": target.get("scenario_name"),
        "description": target.get("scenario_description"),
        "traffic_path": target.get("traffic_path"),
        "scheme": target.get("scheme"),
        "benchmark_path": target.get("benchmark_path"),
        "payload_bytes": payload_bytes(target.get("benchmark_path")),
        "benchmark_engine": target.get("benchmark_engine") or "locust",
        "locust_profile": target.get("locust_profile") or "staircase",
        "capacity_mode": target.get("capacity_mode"),
        "capacity_profile": capacity_profile,
        "connection_mode": target.get("connection_mode"),
        "frontend_tls_termination": bool(target.get("frontend_tls_termination", False)),
        "backend_tls": bool(target.get("backend_tls", False)),
        "backend_reencrypt": bool(target.get("backend_reencrypt", False)),
    }

    manifest: dict[str, Any] = {
        "schema_version": 7,
        "benchmark_id": target.get("benchmark_id") or result_dir.name,
        "captured_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "timing": timing,
        "tool": tool,
        "metadata": cfg.get("metadata") or {},
        "target": target,
        "scenario": scenario,
        "cloud": safe_openstack_metadata(cfg.get("openstack") or {}),
        "observability": {
            "grafana": cfg.get("grafana") or {},
            "prometheus_diagnostics": {
                "status": prometheus_diag.get("status"),
                "collector": prometheus_diag.get("collector"),
                "query_window": prometheus_diag.get("query_window"),
                "domains": prometheus_diag.get("domains"),
                "successful_queries": prometheus_diag.get("successful_queries"),
                "failed_queries": prometheus_diag.get("failed_queries"),
                "summary": prometheus_diag.get("summary") or {},
                "error": prometheus_diag.get("error"),
                "query_errors": prometheus_diag.get("query_errors") or {},
            },
        },
        "network": network_manifest,
        "generator_network": {
            "configured": generator_network_cfg,
            "configured_mode": generator_network_cfg.get("mode", "auto"),
            "resolved_mode": infra.get("resolved_generator_network_mode"),
            "network_name": infra.get("generator_network_name"),
            "subnet_name": infra.get("generator_subnet_name"),
            "cidr": infra.get("generator_network_cidr"),
            "isolated_from_backends": bool(infra.get("generator_network_isolated_from_backends", False)),
            "direct_backend_reachable": bool(infra.get("direct_backend_reachable", True)),
            "master_generator_ip": infra.get("master_generator_ip"),
            "master_workload_ip": infra.get("master_workload_ip"),
        },
        "vm_image": image,
        "load_generator": {
            "master": {"count": 1, "flavor": master_flavor, "configured": vm.get("master") or {}},
            "workers": {
                "count": worker_count,
                "processes_per_vm": processes_per_vm,
                "total_processes": worker_count * processes_per_vm,
                "flavor": worker_flavor,
                "configured": vm.get("locust") or {},
            },
        },
        "backend": {
            "count": int((vm.get("backend") or {}).get("count", 0)),
            "flavor": backend_flavor,
            "configured": vm.get("backend") or {},
            "server": "native nginx",
            "http_port": backend_cfg.get("port"),
            "tls_port": backend_cfg.get("tls_port"),
            "health_path": backend_cfg.get("health_path"),
            "payload_sizes": backend_cfg.get("payload_sizes") or [],
        },
        "workload": (
            {
                "engine": "connection_capacity",
                "capacity_mode": scenario.get("capacity_mode"),
                "capacity_profile": scenario.get("capacity_profile"),
                "levels": effective_capacity_levels,
                "max_levels_per_worker": capacity_cfg.get("max_levels_per_worker") or [],
                "processes_per_vm": capacity_cfg.get("processes_per_vm", 2),
                "ramp_seconds": capacity_cfg.get("ramp_seconds"),
                "hold_seconds": capacity_cfg.get("hold_seconds"),
                "heartbeat_seconds": capacity_cfg.get("heartbeat_seconds"),
                "inter_level_cooldown_seconds": capacity_cfg.get("inter_level_cooldown_seconds"),
                "connect_timeout_seconds": capacity_cfg.get("connect_timeout_seconds"),
                "request_timeout_seconds": capacity_cfg.get("request_timeout_seconds"),
                "open_concurrency_per_worker": capacity_cfg.get("open_concurrency_per_worker"),
                "io_concurrency_per_worker": capacity_cfg.get("io_concurrency_per_worker"),
                "failure_threshold_percent": capacity_cfg.get("failure_threshold_percent"),
                "verify_idle_at_end": capacity_cfg.get("verify_idle_at_end"),
                "abortive_close": capacity_cfg.get("abortive_close"),
                "file_descriptor_limit": capacity_cfg.get("file_descriptor_limit"),
                "source_port_guard_per_worker": capacity_cfg.get("source_port_guard_per_worker"),
                "allow_source_port_overcommit": capacity_cfg.get("allow_source_port_overcommit", False),
                "benchmark_path": scenario["benchmark_path"],
            }
            if scenario.get("benchmark_engine") == "connection_capacity"
            else {
                "engine": "locust",
                "locust_profile": scenario.get("locust_profile"),
                "stages": stages if scenario.get("locust_profile") != "max_rps" else [],
                "total_duration_seconds": (
                    sum(int(s.get("duration_seconds", 0)) for s in stages)
                    if scenario.get("locust_profile") != "max_rps"
                    else None
                ),
                "max_rps": max_rps_cfg if scenario.get("locust_profile") == "max_rps" else None,
                "request_timeout_seconds": locust.get("request_timeout_seconds"),
                "stop_timeout_seconds": locust.get("stop_timeout_seconds"),
                "baseline_direct": locust.get("baseline_direct"),
                "benchmark_path": scenario["benchmark_path"],
                "connection_mode": scenario["connection_mode"],
            }
        ),
        "octavia": {
            "flavor_under_test": target.get("octavia_flavor"),
            "provider": target.get("provider"),
            "listener_protocol": target.get("listener_protocol"),
            "listener_port": target.get("listener_port"),
            "listener_connection_limit": target.get("listener_connection_limit"),
            "listener_timeout_client_data_ms": target.get("listener_timeout_client_data_ms"),
            "listener_timeout_member_data_ms": target.get("listener_timeout_member_data_ms"),
            "pool_protocol": target.get("pool_protocol"),
            "member_port": target.get("member_port"),
            "health_monitor_type": target.get("health_monitor_type"),
            "lb_algorithm": octavia_cfg.get("lb_algorithm"),
            "health_monitor": octavia_cfg.get("health_monitor") or {},
            "traffic_path": scenario["traffic_path"],
            "amphora_inventory_captured_at_utc": target.get("amphora_inventory_captured_at_utc"),
            "amphora_count": target.get("amphora_count"),
            "amphorae": target.get("amphorae") or [],
            "primary_amphora": target.get("primary_amphora") or {},
            "prometheus_libvirt_domains": target.get("prometheus_libvirt_domains") or [],
            "prometheus_libvirt_domain_regex": target.get("prometheus_libvirt_domain_regex"),
        },
        "tls": {
            "enabled": tls_cfg.get("enabled"),
            "key_bits": tls_cfg.get("key_bits"),
            "ca_key_bits": tls_cfg.get("ca_key_bits"),
            "certificate_days": tls_cfg.get("certificate_days"),
            "client_insecure": tls_cfg.get("client_insecure"),
            "backend_protocols": tls_cfg.get("backend_protocols") or [],
            "listener_tls_versions": tls_cfg.get("listener_tls_versions") or [],
            "listener_tls_ciphers": tls_cfg.get("listener_tls_ciphers"),
            "pool_tls_versions": tls_cfg.get("pool_tls_versions") or [],
            "pool_tls_ciphers": tls_cfg.get("pool_tls_ciphers"),
            "frontend_barbican_secret_used": bool(target.get("listener_tls_secret_ref")),
            "backend_ca_barbican_secret_used": bool(target.get("backend_ca_secret_ref")),
            "material": tls_material,
        },
        "metrics": cfg.get("metrics") or {},
        "campaign": cfg.get("campaign") or {},
        "infrastructure": {
            "backend_servers": infra.get("backend_servers") or [],
            "locust_servers": infra.get("locust_servers") or [],
            "master_server": infra.get("master_server") or {},
        },
        "nodes": nodes,
    }

    comparison_basis = {
        "cloud": manifest["cloud"],
        "network": manifest["network"],
        "generator_network": manifest["generator_network"],
        "vm_image": manifest["vm_image"],
        "load_generator": manifest["load_generator"],
        "backend": manifest["backend"],
        "workload": manifest["workload"],
        "scenario": manifest["scenario"],
        "octavia_protocol": {k: v for k, v in manifest["octavia"].items() if k not in {"flavor_under_test", "provider"}},
        "tls": {
            k: v
            for k, v in manifest["tls"].items()
            if not k.endswith("_secret_used") and k != "material"
        },
        "node_runtime": grouped_node_fingerprint(nodes),
        "harness_sha256": tool.get("harness_sha256"),
        "cloud_build": (manifest.get("metadata") or {}).get("cloud_build"),
    }
    manifest["comparison_fingerprint"] = fingerprint(comparison_basis)
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Create and print a historical run specification")
    ap.add_argument("result_dir")
    args = ap.parse_args()
    root = Path(args.result_dir)

    manifest = build_manifest(root)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    (root / "manifest.yml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    md = manifest_markdown(manifest)
    (root / "RUN_MANIFEST.md").write_text(md)

    print("\n" + "=" * 78)
    print("RUN SPECIFICATION")
    print("=" * 78)
    for line in md.splitlines():
        if line.startswith("# ") or line.startswith("## ") or line.startswith("### "):
            continue
        if line.startswith("```") or line.startswith("|") or not line.strip():
            continue
        if line.startswith("- **"):
            print(line.replace("**", "").removeprefix("- "))
    print(f"Full manifest: {root / 'RUN_MANIFEST.md'}")
    print(f"Machine-readable: {root / 'manifest.json'}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()

