#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import pathlib
import shutil
import sys
from typing import Any

import yaml

from topology import VALID_GENERATOR_NETWORK_MODES, resolved_generator_network_mode


def die(msg: str) -> None:
    raise SystemExit(f"config error: {msg}")


def required(cfg: dict[str, Any], dotted: str) -> Any:
    cur: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            die(f"missing {dotted}")
        cur = cur[part]
    if cur in (None, ""):
        die(f"empty {dotted}")
    return cur




def validate_cloud_profile(name: str, value: Any, *, required_profile: bool) -> None:
    if value in (None, ""):
        if required_profile:
            die(f"missing openstack.{name}")
        return
    if not isinstance(value, str) or not value.strip():
        die(
            f"openstack.{name} must be the name of a profile under clouds: in clouds.yaml"
        )

def main() -> None:
    if len(sys.argv) != 2:
        die("usage: validate_config.py CONFIG.yml")
    path = pathlib.Path(sys.argv[1])
    cfg = yaml.safe_load(path.read_text())
    if not isinstance(cfg, dict):
        die("top-level configuration must be a mapping")

    for dotted in (
        "network.name",
        "network.subnet_name",
        "network.cidr",
        "network.external_network",
        "generator_network.mode",
        "ssh.user",
        "ssh.operator_cidr",
        "vm.image",
    ):
        required(cfg, dotted)

    openstack_cfg = cfg.get("openstack") or {}
    validate_cloud_profile("cloud", openstack_cfg.get("cloud"), required_profile=True)
    validate_cloud_profile(
        "admin_cloud", openstack_cfg.get("admin_cloud"), required_profile=False
    )

    cidr = ipaddress.ip_network(cfg["ssh"]["operator_cidr"], strict=False)
    if cidr.version != 4:
        die("ssh.operator_cidr must currently be IPv4")
    if str(cidr) == "0.0.0.0/0":
        die("refusing ssh.operator_cidr=0.0.0.0/0; use your public /32 or trusted CIDR")

    controller_mtu = (cfg.get("ssh") or {}).get("controller_fip_mtu", "auto")
    if str(controller_mtu) != "auto":
        try:
            controller_mtu_int = int(controller_mtu)
        except (TypeError, ValueError):
            die("ssh.controller_fip_mtu must be 'auto' or an integer")
        if not 576 <= controller_mtu_int <= 65535:
            die("ssh.controller_fip_mtu must be between 576 and 65535")
    for key in ("connect_timeout_seconds", "readiness_timeout_seconds", "private_tcp_timeout_seconds", "readiness_serial", "configure_serial", "retries"):
        value = int((cfg.get("ssh") or {}).get(key, 1))
        if value <= 0:
            die(f"ssh.{key} must be > 0")

    for role, key in (("backend", "count"), ("locust", "worker_vms")):
        value = int(cfg["vm"][role][key])
        if value < 1:
            die(f"vm.{role}.{key} must be >= 1")

    ppv = int(cfg["vm"]["locust"]["processes_per_vm"])
    if ppv < 1:
        die("vm.locust.processes_per_vm must be >= 1")

    stages = cfg["locust"]["stages"]
    if not stages:
        die("locust.stages must not be empty")
    for i, stage in enumerate(stages):
        for key in ("users", "duration_seconds", "spawn_rate"):
            if int(stage[key]) <= 0:
                die(f"locust.stages[{i}].{key} must be > 0")

    if not cfg["octavia"].get("flavors"):
        die("octavia.flavors must contain at least one flavor or 'default'")

    traffic_path = (cfg.get("benchmark") or {}).get("traffic_path", "tenant_vip")
    if traffic_path not in {"tenant_vip", "floating_ip"}:
        die("benchmark.traffic_path must be tenant_vip or floating_ip")

    generator_cfg = cfg.get("generator_network") or {}
    generator_mode = str(generator_cfg.get("mode", "auto"))
    if generator_mode not in VALID_GENERATOR_NETWORK_MODES:
        die(
            "generator_network.mode must be one of: "
            + ", ".join(sorted(VALID_GENERATOR_NETWORK_MODES))
        )
    resolved_generator_mode = resolved_generator_network_mode(cfg)
    if resolved_generator_mode != "shared":
        for key in ("name", "subnet_name", "cidr"):
            if generator_cfg.get(key) in (None, ""):
                die(f"generator_network.{key} is required for {resolved_generator_mode}")
        generator_cidr = ipaddress.ip_network(str(generator_cfg["cidr"]), strict=False)
        workload_cidr = ipaddress.ip_network(str(required(cfg, "network.cidr")), strict=False)
        if generator_cidr.version != 4:
            die("generator_network.cidr must currently be IPv4")
        if generator_cidr.overlaps(workload_cidr):
            die("generator_network.cidr must not overlap network.cidr")
    if resolved_generator_mode == "dedicated_external":
        if traffic_path != "floating_ip":
            die("generator_network.mode=dedicated_external requires benchmark.traffic_path=floating_ip")
        if bool(generator_cfg.get("create", True)) and not generator_cfg.get("router_name"):
            die("generator_network.router_name is required when creating dedicated_external topology")
    if (
        resolved_generator_mode == "dedicated_routed"
        and bool(generator_cfg.get("create", True))
        and not bool((cfg.get("network") or {}).get("create", True))
    ):
        die(
            "dedicated_routed with generator_network.create=true requires network.create=true; "
            "otherwise set generator_network.create=false and pre-route the existing generator subnet"
        )

    scenarios = cfg.get("scenarios") or {}
    enabled = scenarios.get("enabled") or []
    catalog = scenarios.get("catalog") or {}
    if not enabled:
        die("scenarios.enabled must contain at least one scenario")
    unknown = [name for name in enabled if name not in catalog]
    if unknown:
        die(f"enabled scenario(s) missing from scenarios.catalog: {', '.join(map(str, unknown))}")

    tls_required = False
    capacity_required = any(
        isinstance(scenario, dict) and str(scenario.get("benchmark_engine", "locust")) == "connection_capacity"
        for scenario in catalog.values()
    )
    for name, scenario in catalog.items():
        if not isinstance(scenario, dict):
            die(f"scenarios.catalog.{name} must be a mapping")
        for key in (
            "scheme",
            "listener_protocol",
            "listener_port",
            "pool_protocol",
            "member_port",
            "health_monitor_type",
            "benchmark_path",
            "connection_mode",
        ):
            if scenario.get(key) in (None, ""):
                die(f"scenario {name} is missing {key}")
        if scenario["scheme"] not in {"http", "https"}:
            die(f"scenario {name}: scheme must be http or https")
        if scenario["connection_mode"] not in {"keepalive", "close"}:
            die(f"scenario {name}: connection_mode must be keepalive or close")
        engine = str(scenario.get("benchmark_engine", "locust"))
        if engine not in {"locust", "connection_capacity"}:
            die(f"scenario {name}: benchmark_engine must be locust or connection_capacity")
        locust_profile = str(scenario.get("locust_profile", "staircase"))
        if locust_profile not in {"staircase", "max_rps"}:
            die(f"scenario {name}: locust_profile must be staircase or max_rps")
        if engine != "locust" and locust_profile != "staircase":
            die(f"scenario {name}: locust_profile is only valid for benchmark_engine=locust")
        capacity_profile = str(scenario.get("capacity_profile", "standard"))
        if capacity_profile not in {"standard", "max"}:
            die(f"scenario {name}: capacity_profile must be standard or max")
        if engine != "connection_capacity" and capacity_profile != "standard":
            die(f"scenario {name}: capacity_profile is only valid for connection_capacity")
        if engine == "connection_capacity":
            if scenario.get("capacity_mode") not in {"idle", "active"}:
                die(f"scenario {name}: connection_capacity scenarios require capacity_mode=idle or active")
            if scenario["connection_mode"] != "keepalive":
                die(f"scenario {name}: connection_capacity scenarios require connection_mode=keepalive")
        for key in ("listener_port", "member_port"):
            port = int(scenario[key])
            if not 1 <= port <= 65535:
                die(f"scenario {name}: {key} must be 1..65535")
        termination = bool(scenario.get("frontend_tls_termination", False))
        backend_tls = bool(scenario.get("backend_tls", False))
        reencrypt = bool(scenario.get("backend_reencrypt", False))
        if termination and scenario["listener_protocol"] != "TERMINATED_HTTPS":
            die(f"scenario {name}: frontend_tls_termination requires listener_protocol=TERMINATED_HTTPS")
        if reencrypt and not backend_tls:
            die(f"scenario {name}: backend_reencrypt requires backend_tls=true")
        if name in enabled and (scenario["scheme"] == "https" or termination or backend_tls):
            tls_required = True

        benchmark_path = str(scenario["benchmark_path"])
        if not benchmark_path.startswith("/"):
            die(f"scenario {name}: benchmark_path must start with /")
        basename = benchmark_path.rsplit("/", 1)[-1]
        if basename.endswith(".bin") and basename[:-4].isdigit():
            size = int(basename[:-4])
            if size not in [int(x) for x in cfg.get("backend", {}).get("payload_sizes", [])]:
                die(f"scenario {name}: payload {size} is not in backend.payload_sizes")


    listener_cfg = (cfg.get("octavia") or {}).get("listener") or {}
    normal_connection_limit = int(listener_cfg.get("connection_limit", 100000))
    capacity_connection_limit = int(listener_cfg.get("capacity_connection_limit", 1000000))
    if normal_connection_limit <= 0:
        die("octavia.listener.connection_limit must be > 0")
    if capacity_connection_limit <= 0:
        die("octavia.listener.capacity_connection_limit must be > 0")
    if capacity_connection_limit < normal_connection_limit:
        die("octavia.listener.capacity_connection_limit must be >= octavia.listener.connection_limit")

    max_rps_required = any(
        isinstance(scenario, dict) and str(scenario.get("locust_profile", "staircase")) == "max_rps"
        for scenario in catalog.values()
    )
    if max_rps_required:
        configured_max_users = int((cfg.get("max_rps") or {}).get("max_users", 0))
        if configured_max_users > 0 and normal_connection_limit < configured_max_users:
            die(
                "octavia.listener.connection_limit must be >= max_rps.max_users "
                "so listener policy does not cap the adaptive RPS search"
            )
    if max_rps_required:
        max_cfg = cfg.get("max_rps") or {}
        for key in ("start_users", "max_users", "spawn_rate", "measure_seconds", "max_search_steps", "search_resolution_users"):
            if float(max_cfg.get(key, 0)) <= 0:
                die(f"max_rps.{key} must be > 0")
        if int(max_cfg.get("max_users", 0)) < int(max_cfg.get("start_users", 0)):
            die("max_rps.max_users must be >= max_rps.start_users")
        if float(max_cfg.get("growth_factor", 0)) <= 1.0:
            die("max_rps.growth_factor must be > 1")
        if float(max_cfg.get("settle_seconds", 0)) < 0:
            die("max_rps.settle_seconds must be >= 0")
        fail_threshold = float(max_cfg.get("failure_threshold_percent", 1.0))
        if not 0 <= fail_threshold < 100:
            die("max_rps.failure_threshold_percent must be >= 0 and < 100")
        if float(max_cfg.get("p99_max_ms", 0)) < 0:
            die("max_rps.p99_max_ms must be >= 0; use 0 to disable the latency gate")
        tolerance = float(max_cfg.get("user_reach_tolerance_percent", 2.0))
        if not 0 <= tolerance < 100:
            die("max_rps.user_reach_tolerance_percent must be >= 0 and < 100")
        if float(max_cfg.get("user_reach_timeout_seconds", 0)) <= 0:
            die("max_rps.user_reach_timeout_seconds must be > 0")

    if capacity_required:
        capacity = cfg.get("connection_capacity") or {}
        levels = capacity.get("levels") or []
        if not levels:
            die("connection_capacity.levels must not be empty when a capacity scenario is enabled")
        try:
            levels = [int(x) for x in levels]
        except (TypeError, ValueError):
            die("connection_capacity.levels must contain integers")
        if any(x <= 0 for x in levels):
            die("connection_capacity.levels must contain only positive integers")
        if levels != sorted(set(levels)):
            die("connection_capacity.levels must be unique and strictly increasing")
        for key in (
            "ramp_seconds",
            "hold_seconds",
            "heartbeat_seconds",
            "connect_timeout_seconds",
            "request_timeout_seconds",
            "open_concurrency_per_worker",
            "io_concurrency_per_worker",
            "file_descriptor_limit",
        ):
            value = float(capacity.get(key, 0))
            if value <= 0:
                die(f"connection_capacity.{key} must be > 0")
        if float(capacity.get("inter_level_cooldown_seconds", 0)) < 0:
            die("connection_capacity.inter_level_cooldown_seconds must be >= 0")
        threshold = float(capacity.get("failure_threshold_percent", 1.0))
        if not 0 <= threshold < 100:
            die("connection_capacity.failure_threshold_percent must be >= 0 and < 100")
        worker_vms = int(cfg["vm"]["locust"]["worker_vms"])
        capacity_processes = int(capacity.get("processes_per_vm", 2))
        if capacity_processes < 1:
            die("connection_capacity.processes_per_vm must be >= 1")
        standard_max_per_worker = (max(levels) + worker_vms - 1) // worker_vms
        max_profile_levels = capacity.get("max_levels_per_worker") or []
        try:
            max_profile_levels = [int(x) for x in max_profile_levels]
        except (TypeError, ValueError):
            die("connection_capacity.max_levels_per_worker must contain integers")
        if not max_profile_levels or any(x <= 0 for x in max_profile_levels):
            die("connection_capacity.max_levels_per_worker must contain positive integers")
        if max_profile_levels != sorted(set(max_profile_levels)):
            die("connection_capacity.max_levels_per_worker must be unique and strictly increasing")
        max_per_worker = max(standard_max_per_worker, max(max_profile_levels))
        max_global_target = max(max(levels), max(max_profile_levels) * worker_vms)
        guard = int(capacity.get("source_port_guard_per_worker", 55000))
        if guard < 1:
            die("connection_capacity.source_port_guard_per_worker must be >= 1")
        if max_per_worker > guard and not bool(capacity.get("allow_source_port_overcommit", False)):
            die(
                "highest connection_capacity level requires about "
                f"{max_per_worker} connections from one worker IP, above the configured source-port guard "
                f"of {guard}; add Locust worker VMs or explicitly set "
                "connection_capacity.allow_source_port_overcommit=true after providing additional source IP capacity"
            )
        fd_limit = int(capacity.get("file_descriptor_limit", 0))
        if fd_limit <= max_per_worker + 1024:
            die(
                "connection_capacity.file_descriptor_limit should exceed the maximum per-worker connection target "
                "by at least 1024 descriptors"
            )
        listener_cfg = (cfg.get("octavia") or {}).get("listener") or {}
        listener_limit = int(listener_cfg.get("capacity_connection_limit", 1000000))
        if listener_limit < max_global_target:
            die(
                "octavia.listener.capacity_connection_limit must be >= the highest effective "
                "connection_capacity level; otherwise the configured listener policy becomes "
                "the measured ceiling"
            )
        hold_ms = float(capacity.get("hold_seconds", 0)) * 1000.0
        client_timeout_ms = int(listener_cfg.get("timeout_client_data_ms", 0))
        if client_timeout_ms <= hold_ms:
            die(
                "octavia.listener.timeout_client_data_ms must exceed connection_capacity.hold_seconds; "
                "otherwise idle-capacity tests measure the inactivity timeout"
            )
        member_timeout_ms = int(listener_cfg.get("timeout_member_data_ms", 0))
        heartbeat_ms = float(capacity.get("heartbeat_seconds", 0)) * 1000.0
        if member_timeout_ms <= heartbeat_ms:
            die(
                "octavia.listener.timeout_member_data_ms must exceed connection_capacity.heartbeat_seconds "
                "for active capacity tests"
            )

    if tls_required and not bool((cfg.get("tls") or {}).get("enabled", False)):
        die("one or more enabled scenarios use TLS but tls.enabled is false")
    if bool((cfg.get("tls") or {}).get("enabled", False)) and shutil.which("openssl") is None:
        die("tls.enabled=true requires the openssl command on the Ansible controller")

    campaign = cfg.get("campaign", {})
    if int(campaign.get("repetitions", 3)) < 1:
        die("campaign.repetitions must be >= 1")
    if int(campaign.get("baseline_repetitions", 1)) < 0:
        die("campaign.baseline_repetitions must be >= 0")
    if float(campaign.get("cooldown_seconds", 15)) < 0:
        die("campaign.cooldown_seconds must be >= 0")
    if int(campaign.get("scenario_setup_attempts", 2)) < 1:
        die("campaign.scenario_setup_attempts must be >= 1")
    if float(campaign.get("scenario_setup_retry_delay_seconds", 10)) < 0:
        die("campaign.scenario_setup_retry_delay_seconds must be >= 0")

    print(
        f"configuration OK: {path}; traffic_path={traffic_path}; "
        f"generator_network={generator_mode}->{resolved_generator_mode}; "
        f"scenarios={','.join(map(str, enabled))}"
    )


if __name__ == "__main__":
    main()
