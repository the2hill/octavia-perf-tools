#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import yaml


def load_metrics(result_dir: Path) -> pd.DataFrame:
    frames = []
    for path in result_dir.glob("raw/*/metrics.csv"):
        try:
            df = pd.read_csv(path)
        except (pd.errors.EmptyDataError, FileNotFoundError):
            continue
        df["node"] = path.parent.name
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_many(paths: list[Path], node_from_parent: bool = True) -> pd.DataFrame:
    frames = []
    for path in paths:
        try:
            df = pd.read_csv(path)
        except (pd.errors.EmptyDataError, FileNotFoundError):
            continue
        if node_from_parent:
            df["node"] = path.parent.name
        df["source_file"] = path.name
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def save_plot(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def metric_charts(root: Path, charts: Path, cfg: dict) -> tuple[pd.DataFrame, list[dict]]:
    metrics = load_metrics(root)
    bottlenecks: list[dict] = []
    if metrics.empty:
        return metrics, bottlenecks

    fig, ax = plt.subplots(figsize=(10, 5))
    for node, group in metrics.groupby("node"):
        ax.plot(pd.to_datetime(group["timestamp_epoch"], unit="s"), group["cpu_percent"], label=node)
        peak = float(group["cpu_percent"].max())
        if peak >= float(cfg["metrics"]["cpu_warn_percent"]):
            bottlenecks.append({"node": node, "peak_cpu_percent": peak})
    ax.set_title("Node CPU utilization")
    ax.set_xlabel("Time")
    ax.set_ylabel("CPU %")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.25)
    save_plot(fig, charts / "cpu.png")

    fig, ax = plt.subplots(figsize=(10, 5))
    for node, group in metrics.groupby("node"):
        ax.plot(pd.to_datetime(group["timestamp_epoch"], unit="s"), group["tx_bytes_per_sec"] / 1e6, label=node)
    ax.set_title("Node transmit throughput")
    ax.set_xlabel("Time")
    ax.set_ylabel("MB/s")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.25)
    save_plot(fig, charts / "network_tx.png")
    return metrics, bottlenecks


def base_summary(target: dict, manifest: dict) -> dict:
    scenario = manifest.get("scenario") or {}
    worker_spec = ((manifest.get("load_generator") or {}).get("workers") or {})
    worker_flavor = worker_spec.get("flavor") or {}
    backend_spec = manifest.get("backend") or {}
    backend_flavor = backend_spec.get("flavor") or {}
    image_spec = manifest.get("vm_image") or {}
    cloud_spec = manifest.get("cloud") or {}
    octavia_spec = manifest.get("octavia") or {}
    workload_spec = manifest.get("workload") or {}
    prometheus_diag = ((manifest.get("observability") or {}).get("prometheus_diagnostics") or {})
    prometheus_summary = prometheus_diag.get("summary") or {}
    return {
        "benchmark_id": target.get("benchmark_id"),
        "suite_id": target.get("suite_id") or target.get("campaign_id"),
        "baseline_for_flavor": target.get("baseline_for_flavor"),
        "target_kind": target.get("target_kind"),
        "benchmark_engine": scenario.get("benchmark_engine") or target.get("benchmark_engine") or "locust",
        "locust_profile": scenario.get("locust_profile") or target.get("locust_profile") or "staircase",
        "capacity_profile": scenario.get("capacity_profile") or target.get("capacity_profile") or "standard",
        "scenario_name": scenario.get("name") or target.get("scenario_name"),
        "scenario_description": scenario.get("description") or target.get("scenario_description"),
        "traffic_path": scenario.get("traffic_path") or target.get("traffic_path"),
        "scheme": scenario.get("scheme") or target.get("scheme"),
        "benchmark_path": scenario.get("benchmark_path") or target.get("benchmark_path"),
        "payload_bytes": scenario.get("payload_bytes"),
        "connection_mode": scenario.get("connection_mode") or target.get("connection_mode"),
        "capacity_mode": scenario.get("capacity_mode") or target.get("capacity_mode"),
        "frontend_tls_termination": scenario.get("frontend_tls_termination", False),
        "backend_tls": scenario.get("backend_tls", False),
        "backend_reencrypt": scenario.get("backend_reencrypt", False),
        "listener_protocol": octavia_spec.get("listener_protocol"),
        "listener_port": octavia_spec.get("listener_port"),
        "listener_connection_limit": octavia_spec.get("listener_connection_limit"),
        "listener_timeout_client_data_ms": octavia_spec.get("listener_timeout_client_data_ms"),
        "listener_timeout_member_data_ms": octavia_spec.get("listener_timeout_member_data_ms"),
        "pool_protocol": octavia_spec.get("pool_protocol"),
        "member_port": octavia_spec.get("member_port"),
        "octavia_flavor": target.get("octavia_flavor"),
        "target_host": target.get("target_host"),
        "octavia_provider": target.get("provider"),
        "octavia_flavor_id": target.get("flavor_id"),
        "amphora_inventory_captured_at_utc": target.get("amphora_inventory_captured_at_utc"),
        "amphora_count": target.get("amphora_count"),
        "amphorae": target.get("amphorae") or [],
        "primary_amphora": target.get("primary_amphora") or {},
        "amphora_id": target.get("amphora_id"),
        "amphora_role": target.get("amphora_role"),
        "amphora_status": target.get("amphora_status"),
        "amphora_compute_id": target.get("amphora_compute_id"),
        "amphora_instance_name": target.get("amphora_instance_name"),
        "amphora_compute_host": target.get("amphora_compute_host"),
        "amphora_hypervisor_hostname": target.get("amphora_hypervisor_hostname"),
        "amphora_availability_zone": target.get("amphora_availability_zone"),
        "amphora_lb_network_ip": target.get("amphora_lb_network_ip"),
        "amphora_vrrp_ip": target.get("amphora_vrrp_ip"),
        "prometheus_libvirt_domains": target.get("prometheus_libvirt_domains") or [],
        "prometheus_libvirt_domain_regex": target.get("prometheus_libvirt_domain_regex"),
        "prometheus_diagnostics_status": prometheus_diag.get("status"),
        "amphora_avg_cpu_cores": prometheus_summary.get("avg_cpu_cores"),
        "amphora_peak_cpu_cores": prometheus_summary.get("peak_cpu_cores"),
        "amphora_avg_cpu_percent": prometheus_summary.get("avg_cpu_percent"),
        "amphora_peak_cpu_percent": prometheus_summary.get("peak_cpu_percent"),
        "amphora_allocated_vcpus": prometheus_summary.get("allocated_vcpus"),
        "amphora_hottest_vcpu_percent": prometheus_summary.get("hottest_vcpu_percent"),
        "amphora_peak_vcpu_delay_seconds_per_second": prometheus_summary.get("peak_vcpu_delay_seconds_per_second"),
        "amphora_peak_vcpu_wait_seconds_per_second": prometheus_summary.get("peak_vcpu_wait_seconds_per_second"),
        "amphora_peak_rx_bytes_per_second": prometheus_summary.get("peak_rx_bytes_per_second"),
        "amphora_peak_tx_bytes_per_second": prometheus_summary.get("peak_tx_bytes_per_second"),
        "amphora_peak_rx_packets_per_second": prometheus_summary.get("peak_rx_packets_per_second"),
        "amphora_peak_tx_packets_per_second": prometheus_summary.get("peak_tx_packets_per_second"),
        "amphora_peak_rx_errors_per_second": prometheus_summary.get("peak_rx_errors_per_second"),
        "amphora_peak_tx_errors_per_second": prometheus_summary.get("peak_tx_errors_per_second"),
        "campaign_label": (manifest.get("metadata") or {}).get("campaign_label"),
        "cloud_build": (manifest.get("metadata") or {}).get("cloud_build"),
        "load_test_started_at_utc": (manifest.get("timing") or {}).get("load_test_started_at_utc"),
        "load_test_completed_at_utc": (manifest.get("timing") or {}).get("load_test_completed_at_utc"),
        "environment_label": cloud_spec.get("environment_label"),
        "generator_network_mode": (manifest.get("generator_network") or {}).get("resolved_mode"),
        "generator_network_name": (manifest.get("generator_network") or {}).get("network_name"),
        "generator_network_cidr": (manifest.get("generator_network") or {}).get("cidr"),
        "generator_network_isolated_from_backends": (manifest.get("generator_network") or {}).get("isolated_from_backends"),
        "image_name": image_spec.get("name") or image_spec.get("requested"),
        "image_id": image_spec.get("id"),
        "generator_worker_vms": worker_spec.get("count"),
        "generator_processes_per_vm": worker_spec.get("processes_per_vm"),
        "generator_total_processes": worker_spec.get("total_processes"),
        "capacity_processes_per_vm": workload_spec.get("processes_per_vm") if workload_spec.get("engine") == "connection_capacity" else None,
        "generator_flavor": worker_flavor.get("name"),
        "generator_vcpus_per_vm": worker_flavor.get("vcpus"),
        "generator_ram_mb_per_vm": worker_flavor.get("ram_mb"),
        "backend_count": backend_spec.get("count"),
        "backend_flavor": backend_flavor.get("name"),
        "backend_vcpus_per_vm": backend_flavor.get("vcpus"),
        "backend_ram_mb_per_vm": backend_flavor.get("ram_mb"),
        "scheduled_duration_seconds": workload_spec.get("total_duration_seconds"),
        "spec_fingerprint": manifest.get("comparison_fingerprint"),
    }


def report_locust(root: Path, charts: Path, target: dict, cfg: dict, manifest: dict, bottlenecks: list[dict]) -> dict:
    hist_path = root / "raw/master/locust_stats_history.csv"
    stats_path = root / "raw/master/locust_stats.csv"
    if not hist_path.exists():
        raise SystemExit(f"missing {hist_path}")
    hist = pd.read_csv(hist_path)
    agg = hist[hist["Name"] == "Aggregated"].copy()
    if agg.empty:
        agg = hist.copy()
    agg["Timestamp"] = pd.to_datetime(agg["Timestamp"], unit="s", errors="coerce")

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(agg["Timestamp"], agg["Requests/s"])
    ax.set_title("Request rate")
    ax.set_xlabel("Time")
    ax.set_ylabel("Requests/s")
    ax.grid(True, alpha=0.25)
    save_plot(fig, charts / "rps.png")

    latency_cols = [c for c in ["50%", "95%", "99%"] if c in agg.columns]
    if latency_cols:
        fig, ax = plt.subplots(figsize=(10, 5))
        for col in latency_cols:
            ax.plot(agg["Timestamp"], agg[col], label=col)
        ax.set_title("Response latency percentiles")
        ax.set_xlabel("Time")
        ax.set_ylabel("Milliseconds")
        ax.legend()
        ax.grid(True, alpha=0.25)
        save_plot(fig, charts / "latency.png")

    scenario = manifest.get("scenario") or {}
    payload_size = scenario.get("payload_bytes")
    if payload_size and "Requests/s" in agg:
        agg["estimated_payload_gbps"] = agg["Requests/s"] * float(payload_size) * 8 / 1e9
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(agg["Timestamp"], agg["estimated_payload_gbps"])
        ax.set_title("Estimated application payload throughput")
        ax.set_xlabel("Time")
        ax.set_ylabel("Gb/s (payload only)")
        ax.grid(True, alpha=0.25)
        save_plot(fig, charts / "payload-throughput.png")

    stats = pd.read_csv(stats_path) if stats_path.exists() else pd.DataFrame()
    aggregated = stats[stats["Name"] == "Aggregated"] if not stats.empty and "Name" in stats else pd.DataFrame()
    summary_row = aggregated.iloc[0].to_dict() if not aggregated.empty else {}
    peak_rps = float(agg["Requests/s"].max()) if "Requests/s" in agg else None
    estimated_payload_gbps = peak_rps * float(payload_size) * 8 / 1e9 if peak_rps is not None and payload_size else None

    max_rps_result = {
        "max_sustainable_rps": None,
        "max_sustainable_rps_users": None,
        "max_rps_max_tested_users": None,
        "max_rps_limit_reached": None,
        "max_rps_generator_limited": None,
        "max_rps_search_steps": None,
        "max_rps_best_p99_ms": None,
        "max_rps_best_failure_percent": None,
        "validity_warnings": [],
    }
    if scenario.get("locust_profile") == "max_rps":
        search_path = root / "raw/master/max-rps-stages.csv"
        if not search_path.exists():
            raise SystemExit(f"missing {search_path} for max_rps scenario")
        search = pd.read_csv(search_path)
        if search.empty:
            raise SystemExit("max-rps-stages.csv is empty")
        for col in ["target_users", "actual_users", "average_rps", "failure_percent", "p99_ms"]:
            search[col] = pd.to_numeric(search[col], errors="coerce")
        passed = search[search["passed"].astype(str).str.lower().isin(["true", "1", "yes"])].copy()
        failed = search[~search.index.isin(passed.index)].copy()
        failure_reasons = failed.get("failure_reasons", pd.Series(dtype=str)).fillna("").astype(str)
        generator_limited = bool(failure_reasons.str.contains("user_reach_timeout", regex=False).any())
        quality_failed = failed[~failure_reasons.str.contains("user_reach_timeout", regex=False)]
        if passed.empty:
            max_rps_result["validity_warnings"].append("No adaptive max-RPS search level satisfied the configured quality threshold.")
        else:
            best = passed.loc[passed["average_rps"].idxmax()]
            max_rps_result.update(
                {
                    "max_sustainable_rps": float(best["average_rps"]),
                    "max_sustainable_rps_users": int(best["target_users"]),
                    "max_rps_best_p99_ms": float(best["p99_ms"]) if pd.notna(best["p99_ms"]) else None,
                    "max_rps_best_failure_percent": float(best["failure_percent"]),
                }
            )
        max_rps_result["max_rps_max_tested_users"] = int(search["target_users"].max())
        max_rps_result["max_rps_limit_reached"] = bool(not quality_failed.empty)
        max_rps_result["max_rps_generator_limited"] = generator_limited
        max_rps_result["max_rps_search_steps"] = int(len(search))
        if generator_limited:
            max_rps_result["validity_warnings"].append(
                "Generator fleet could not reach at least one requested Locust user target before max_rps.user_reach_timeout_seconds; treat the reported RPS as generator-bounded until client capacity is increased."
            )
        if failed.empty:
            max_rps_result["validity_warnings"].append(
                "Adaptive search reached max_rps.max_users without a failing quality level; reported RPS is a demonstrated lower bound, not a bounded ceiling."
            )

        fig, ax = plt.subplots(figsize=(10, 5))
        if not passed.empty:
            ax.plot(passed["target_users"], passed["average_rps"], marker="o", linestyle="none", label="Passing")
        if not failed.empty:
            ax.plot(failed["target_users"], failed["average_rps"], marker="x", linestyle="none", label="Failing")
        ax.set_title("Adaptive max-RPS search")
        ax.set_xlabel("Concurrent Locust users")
        ax.set_ylabel("Measured average requests/s")
        ax.legend()
        ax.grid(True, alpha=0.25)
        save_plot(fig, charts / "max-rps-search.png")

    summary = base_summary(target, manifest)
    summary.update(
        {
            "requests": summary_row.get("Request Count"),
            "failures": summary_row.get("Failure Count"),
            "average_rps": summary_row.get("Requests/s"),
            "average_response_ms": summary_row.get("Average Response Time"),
            "p95_ms": summary_row.get("95%"),
            "p99_ms": summary_row.get("99%"),
            "peak_rps_history": peak_rps,
            "estimated_peak_payload_gbps": estimated_payload_gbps,
            "approx_peak_connections_per_second": peak_rps if scenario.get("connection_mode") == "close" else None,
            "max_sustainable_connections": None,
            "peak_established_connections": None,
            "max_tested_connections": None,
            "capacity_limit_reached": None,
            "peak_connection_establishment_rate_cps": None,
            **max_rps_result,
            "bottleneck_warnings": bottlenecks,
        }
    )
    return summary


def report_capacity(root: Path, charts: Path, target: dict, cfg: dict, manifest: dict, bottlenecks: list[dict]) -> dict:
    capacity_paths = list(root.glob("raw/*/connection-capacity-*.csv"))
    if not capacity_paths:
        raise SystemExit("missing distributed connection-capacity CSV files")
    cap = load_many(capacity_paths)
    if cap.empty:
        raise SystemExit("connection-capacity CSV files are empty")
    error_df = load_many(list(root.glob("raw/*/connection-errors-*.csv")))
    error_counts: dict[str, int] = {}
    validity_warnings: list[str] = []
    if not error_df.empty:
        error_df["count"] = pd.to_numeric(error_df["count"], errors="coerce").fillna(0)
        for error, group in error_df.groupby("error"):
            error_counts[str(error)] = int(group["count"].sum())
        if any(k.startswith("oserror:99") for k in error_counts):
            validity_warnings.append("generator reported EADDRNOTAVAIL; source IP/ephemeral-port capacity may be exhausted")
        if any(k.startswith("oserror:24") or k.startswith("oserror:23") for k in error_counts):
            validity_warnings.append("generator reported file-descriptor exhaustion (EMFILE/ENFILE)")
        if any(k.startswith("oserror:12") for k in error_counts):
            validity_warnings.append("generator reported ENOMEM; client memory pressure may be limiting the run")
    for col in ["target_global", "target_worker", "attempted", "established", "establish_failed", "surviving", "survival_failed", "ramp_elapsed_seconds", "established_per_second"]:
        cap[col] = pd.to_numeric(cap[col], errors="coerce")

    grouped = (
        cap.groupby("target_global", as_index=False)
        .agg(
            target_worker_sum=("target_worker", "sum"),
            attempted=("attempted", "sum"),
            established=("established", "sum"),
            establish_failed=("establish_failed", "sum"),
            surviving=("surviving", "sum"),
            survival_failed=("survival_failed", "sum"),
            ramp_elapsed_seconds=("ramp_elapsed_seconds", "max"),
        )
        .sort_values("target_global")
    )
    grouped["established_percent"] = grouped["established"] / grouped["target_global"] * 100.0
    grouped["survival_percent"] = grouped["surviving"] / grouped["established"].replace(0, pd.NA) * 100.0
    grouped["establishment_rate_cps"] = grouped["established"] / grouped["ramp_elapsed_seconds"].replace(0, pd.NA)

    latency = load_many(list(root.glob("raw/*/connection-latencies-*.csv")))
    if not latency.empty:
        latency["target_global"] = pd.to_numeric(latency["target_global"], errors="coerce")
        latency["latency_ms"] = pd.to_numeric(latency["latency_ms"], errors="coerce")
        q = latency.groupby("target_global")["latency_ms"].quantile([0.50, 0.95, 0.99]).unstack()
        q.columns = ["establish_p50_ms", "establish_p95_ms", "establish_p99_ms"]
        grouped = grouped.merge(q.reset_index(), on="target_global", how="left")
    else:
        for c in ["establish_p50_ms", "establish_p95_ms", "establish_p99_ms"]:
            grouped[c] = pd.NA

    grouped.to_csv(root / "connection-capacity-summary.csv", index=False)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(grouped["target_global"], grouped["established"], marker="o", label="Established")
    ax.plot(grouped["target_global"], grouped["surviving"], marker="o", label="Surviving after hold")
    ax.plot(grouped["target_global"], grouped["target_global"], linestyle="--", label="Target")
    ax.set_title("Concurrent connection capacity")
    ax.set_xlabel("Requested simultaneous connections")
    ax.set_ylabel("Connections")
    ax.legend()
    ax.grid(True, alpha=0.25)
    save_plot(fig, charts / "connection-capacity.png")

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(grouped["target_global"], grouped["established_percent"], marker="o", label="Established %")
    ax.plot(grouped["target_global"], grouped["survival_percent"], marker="o", label="Survived hold %")
    ax.axhline(100.0 - float(cfg.get("connection_capacity", {}).get("failure_threshold_percent", 1.0)), linestyle="--", label="Sustainable threshold")
    ax.set_title("Connection success and survival")
    ax.set_xlabel("Requested simultaneous connections")
    ax.set_ylabel("Percent")
    ax.set_ylim(0, 101)
    ax.legend()
    ax.grid(True, alpha=0.25)
    save_plot(fig, charts / "connection-success.png")

    fig, ax = plt.subplots(figsize=(10, 5))
    for col, label in [("establish_p50_ms", "p50"), ("establish_p95_ms", "p95"), ("establish_p99_ms", "p99")]:
        if grouped[col].notna().any():
            ax.plot(grouped["target_global"], grouped[col], marker="o", label=label)
    ax.set_title("Connection establishment latency")
    ax.set_xlabel("Requested simultaneous connections")
    ax.set_ylabel("Milliseconds")
    ax.legend()
    ax.grid(True, alpha=0.25)
    save_plot(fig, charts / "connection-establishment-latency.png")

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(grouped["target_global"], grouped["establishment_rate_cps"], marker="o")
    ax.set_title("Observed connection establishment rate during capacity ramp")
    ax.set_xlabel("Requested simultaneous connections")
    ax.set_ylabel("Established connections/s")
    ax.grid(True, alpha=0.25)
    save_plot(fig, charts / "connection-establishment-rate.png")

    threshold = float(cfg.get("connection_capacity", {}).get("failure_threshold_percent", 1.0))
    ordered = grouped.sort_values("target_global").reset_index(drop=True)
    passes = (
        (ordered["established_percent"] >= 100.0 - threshold)
        & (ordered["survival_percent"].fillna(0) >= 100.0 - threshold)
    )
    # A sustainable staircase is contiguous from the lowest level. If a lower level
    # fails and a higher one later passes due to noise, do not report the higher
    # point as the demonstrated capacity ceiling.
    max_sustainable = 0
    for row, passed in zip(ordered.itertuples(index=False), passes.tolist()):
        if not passed:
            break
        max_sustainable = int(row.target_global)
    max_tested = int(ordered["target_global"].max())
    peak_established = int(ordered["established"].max())
    capacity_limit_reached = max_sustainable < max_tested
    highest = ordered.iloc[-1]
    capacity_profile = (manifest.get("scenario") or {}).get("capacity_profile") or target.get("capacity_profile") or "standard"
    if capacity_profile == "max" and not capacity_limit_reached:
        validity_warnings.append(
            "Max-connection profile passed through the generator source-port safety ceiling; Octavia capacity is at least the reported value. Add generator VMs/source IPs to search higher."
        )
    if passes.any() and not passes.is_monotonic_decreasing:
        validity_warnings.append(
            "Connection-capacity levels were non-monotonic (a higher level passed after a lower level failed); "
            "max sustainable connections is limited to the contiguous passing staircase."
        )

    summary = base_summary(target, manifest)
    summary.update(
        {
            "requests": None,
            "failures": int(grouped["establish_failed"].sum() + grouped["survival_failed"].sum()),
            "average_rps": None,
            "average_response_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "peak_rps_history": None,
            "estimated_peak_payload_gbps": None,
            "approx_peak_connections_per_second": None,
            "max_sustainable_connections": max_sustainable,
            "peak_established_connections": peak_established,
            "max_tested_connections": max_tested,
            "capacity_limit_reached": bool(capacity_limit_reached),
            "highest_level_established_percent": float(highest["established_percent"]),
            "highest_level_survival_percent": float(highest["survival_percent"]) if pd.notna(highest["survival_percent"]) else None,
            "peak_connection_establishment_rate_cps": float(grouped["establishment_rate_cps"].max()),
            "capacity_failure_threshold_percent": threshold,
            "capacity_profile": capacity_profile,
            "generator_safe_connection_ceiling": max_tested if capacity_profile == "max" else None,
            "max_sustainable_rps": None,
            "max_sustainable_rps_users": None,
            "max_rps_max_tested_users": None,
            "max_rps_limit_reached": None,
            "max_rps_generator_limited": None,
            "max_rps_search_steps": None,
            "max_rps_best_p99_ms": None,
            "max_rps_best_failure_percent": None,
            "connection_error_counts": error_counts,
            "validity_warnings": validity_warnings,
            "bottleneck_warnings": bottlenecks,
        }
    )
    return summary


def write_markdown(root: Path, summary: dict) -> None:
    warning_text = "None."
    if summary.get("bottleneck_warnings"):
        warning_text = ", ".join(
            f"{x['node']} peak CPU {x['peak_cpu_percent']:.1f}%" for x in summary["bottleneck_warnings"]
        )

    if summary["benchmark_engine"] == "connection_capacity":
        if summary.get("capacity_limit_reached"):
            ceiling_text = f"Observed sustainable connection ceiling: **{summary['max_sustainable_connections']:,}**"
        elif summary.get("capacity_profile") == "max":
            ceiling_text = (
                f"Generator-safe ceiling reached; Octavia demonstrated at least **{summary['max_sustainable_connections']:,}** "
                "sustainable connections. Add generator VMs/source IPs to search higher."
            )
        else:
            ceiling_text = f"No ceiling reached; demonstrated at least **{summary['max_sustainable_connections']:,}** sustainable connections"
        md = f"""# Octavia connection-capacity result: {summary['benchmark_id']}

- Scenario: **`{summary['scenario_name']}`** - {summary['scenario_description']}
- Capacity mode: **`{summary['capacity_mode']}`**
- Traffic path: **`{summary['traffic_path']}`**
- Generator network: **`{summary['generator_network_mode']}`** on `{summary['generator_network_name']}` (`{summary['generator_network_cidr']}`)
- Datapath: `{summary['listener_protocol']}:{summary['listener_port']}` -> `{summary['pool_protocol']}:{summary['member_port']}`
- TLS: frontend termination={summary['frontend_tls_termination']}, backend TLS={summary['backend_tls']}, re-encryption={summary['backend_reencrypt']}
- {ceiling_text}
- Maximum target tested: **{summary['max_tested_connections']:,}**
- Peak established in any level: **{summary['peak_established_connections']:,}**
- Peak observed establishment rate during ramps: **{summary['peak_connection_establishment_rate_cps']:,.1f} connections/s**
- Sustainable-level failure threshold: **{summary['capacity_failure_threshold_percent']}%**
- Generator/backend CPU warnings: **{warning_text}**
- Generator validity warnings: **{'; '.join(summary.get('validity_warnings') or []) or 'None.'}**
- Comparison fingerprint: **`{summary.get('spec_fingerprint') or 'n/a'}`**

## Amphora Prometheus diagnostics

- Collection status: **`{summary.get('prometheus_diagnostics_status') or 'not collected'}`**
- CPU: avg **{summary.get('amphora_avg_cpu_cores') if summary.get('amphora_avg_cpu_cores') is not None else 'n/a'}** cores; peak **{summary.get('amphora_peak_cpu_cores') if summary.get('amphora_peak_cpu_cores') is not None else 'n/a'}** cores; hottest vCPU **{summary.get('amphora_hottest_vcpu_percent') if summary.get('amphora_hottest_vcpu_percent') is not None else 'n/a'}%**
- Network: peak RX/TX **{summary.get('amphora_peak_rx_packets_per_second') if summary.get('amphora_peak_rx_packets_per_second') is not None else 'n/a'} / {summary.get('amphora_peak_tx_packets_per_second') if summary.get('amphora_peak_tx_packets_per_second') is not None else 'n/a'} pps**
- Scheduler: peak vCPU delay/wait **{summary.get('amphora_peak_vcpu_delay_seconds_per_second') if summary.get('amphora_peak_vcpu_delay_seconds_per_second') is not None else 'n/a'} / {summary.get('amphora_peak_vcpu_wait_seconds_per_second') if summary.get('amphora_peak_vcpu_wait_seconds_per_second') is not None else 'n/a'} s/s**

Full raw query results are in `prometheus-diagnostics.json`.

## Run specification

The complete generator/backend/OpenStack/TLS/socket-limit snapshot is in [`RUN_MANIFEST.md`](RUN_MANIFEST.md). The aggregated per-level connection data is in `connection-capacity-summary.csv`.

## Charts

![Connection capacity](charts/connection-capacity.png)

![Connection success](charts/connection-success.png)

![Connection establishment latency](charts/connection-establishment-latency.png)

![Connection establishment rate](charts/connection-establishment-rate.png)

![CPU](charts/cpu.png)

![Network TX](charts/network_tx.png)

## Interpretation

`idle` capacity holds established frontend sockets without application traffic during the hold interval, then verifies them with a request at the end. `active` capacity sends periodic requests on every held keepalive connection, exercising frontend and backend connection state. A result at the highest configured level is a lower bound, not a discovered limit. Treat a lower ceiling as Octavia-specific only when generator/backend CPU, file descriptors, source ports, and network bandwidth retain headroom.
"""
    else:
        extras = []
        if summary.get("max_sustainable_rps") is not None:
            if summary.get("max_rps_generator_limited"):
                bound_word = "generator-bounded"
            else:
                bound_word = "bounded" if summary.get("max_rps_limit_reached") else "lower-bound"
            extras.append(
                f"- Max sustainable RPS ({bound_word} search): **{summary['max_sustainable_rps']:,.1f}** "
                f"at **{summary['max_sustainable_rps_users']:,}** concurrent users"
            )
            extras.append(
                f"- Max-RPS search: **{summary.get('max_rps_search_steps')}** measured levels; "
                f"highest user target tested **{summary.get('max_rps_max_tested_users'):,}**"
            )
        if summary.get("estimated_peak_payload_gbps") is not None:
            extras.append(f"- Estimated peak application payload throughput: **{summary['estimated_peak_payload_gbps']:,.3f} Gb/s**")
        if summary.get("approx_peak_connections_per_second") is not None:
            extras.append(f"- Approximate peak new connection rate: **{summary['approx_peak_connections_per_second']:,.1f} connections/s**")
        extras_text = "\n".join(extras)
        throughput_chart = "\n![Payload throughput](charts/payload-throughput.png)\n" if summary.get("payload_bytes") else ""
        max_rps_chart = "\n![Adaptive max-RPS search](charts/max-rps-search.png)\n" if summary.get("locust_profile") == "max_rps" else ""
        md = f"""# Octavia performance result: {summary['benchmark_id']}

- Scenario: **`{summary['scenario_name']}`** - {summary['scenario_description']}
- Traffic path: **`{summary['traffic_path']}`**
- Generator network: **`{summary['generator_network_mode']}`** on `{summary['generator_network_name']}` (`{summary['generator_network_cidr']}`); isolated from backend tenant net={summary['generator_network_isolated_from_backends']}
- Datapath: `{summary['listener_protocol']}:{summary['listener_port']}` -> `{summary['pool_protocol']}:{summary['member_port']}`
- TLS: frontend termination={summary['frontend_tls_termination']}, backend TLS={summary['backend_tls']}, re-encryption={summary['backend_reencrypt']}
- Connection mode: **`{summary['connection_mode']}`**; payload: **`{summary['benchmark_path']}`**
- Target: `{summary['target_kind']}` / flavor `{summary['octavia_flavor']}`
- Peak observed RPS: **{summary['peak_rps_history'] or 0:,.1f}**
- Aggregate average RPS: **{summary['average_rps'] or 0}**
- Aggregate p95 latency: **{summary['p95_ms'] or 'n/a'} ms**
- Aggregate p99 latency: **{summary['p99_ms'] or 'n/a'} ms**
- Failures: **{summary['failures'] or 0}**
{extras_text}
- Client/backend CPU warnings: **{warning_text}**
- Search validity warnings: **{'; '.join(summary.get('validity_warnings') or []) or 'None.'}**
- Comparison fingerprint: **`{summary.get('spec_fingerprint') or 'n/a'}`**

## Amphora Prometheus diagnostics

- Collection status: **`{summary.get('prometheus_diagnostics_status') or 'not collected'}`**
- CPU: avg **{summary.get('amphora_avg_cpu_cores') if summary.get('amphora_avg_cpu_cores') is not None else 'n/a'}** cores; peak **{summary.get('amphora_peak_cpu_cores') if summary.get('amphora_peak_cpu_cores') is not None else 'n/a'}** cores; hottest vCPU **{summary.get('amphora_hottest_vcpu_percent') if summary.get('amphora_hottest_vcpu_percent') is not None else 'n/a'}%**
- Network: peak RX/TX **{summary.get('amphora_peak_rx_packets_per_second') if summary.get('amphora_peak_rx_packets_per_second') is not None else 'n/a'} / {summary.get('amphora_peak_tx_packets_per_second') if summary.get('amphora_peak_tx_packets_per_second') is not None else 'n/a'} pps**
- Scheduler: peak vCPU delay/wait **{summary.get('amphora_peak_vcpu_delay_seconds_per_second') if summary.get('amphora_peak_vcpu_delay_seconds_per_second') is not None else 'n/a'} / {summary.get('amphora_peak_vcpu_wait_seconds_per_second') if summary.get('amphora_peak_vcpu_wait_seconds_per_second') is not None else 'n/a'} s/s**

Full raw query results are in `prometheus-diagnostics.json`.

## Run specification

The complete generator/backend/OpenStack/TLS/software snapshot is in [`RUN_MANIFEST.md`](RUN_MANIFEST.md), with machine-readable copies in `manifest.yml` and `manifest.json`.

## Charts

![Request rate](charts/rps.png)

![Latency](charts/latency.png)
{max_rps_chart}{throughput_chart}
![CPU](charts/cpu.png)

![Network TX](charts/network_tx.png)

## Interpretation

Treat an Octavia ceiling as credible only when Locust workers and backend members retain CPU/network headroom. For `connection_mode=close`, request rate is an approximation of new TCP connection rate because each request asks the server to close the connection. Payload-throughput values are application-payload estimates and do not include Ethernet/IP/TCP/TLS overhead.
"""
    (root / "REPORT.md").write_text(md)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result_dir")
    args = ap.parse_args()
    root = Path(args.result_dir)
    charts = root / "charts"
    charts.mkdir(exist_ok=True)

    target = yaml.safe_load((root / "target.yml").read_text())
    cfg = yaml.safe_load((root / "config-effective.yml").read_text())
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    _, bottlenecks = metric_charts(root, charts, cfg)

    engine = (manifest.get("scenario") or {}).get("benchmark_engine") or target.get("benchmark_engine") or "locust"
    if engine == "connection_capacity":
        summary = report_capacity(root, charts, target, cfg, manifest, bottlenecks)
    else:
        summary = report_locust(root, charts, target, cfg, manifest, bottlenecks)

    (root / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    write_markdown(root, summary)
    print(root / "REPORT.md")


if __name__ == "__main__":
    main()

