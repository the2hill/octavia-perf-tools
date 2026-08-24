#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import matplotlib.pyplot as plt
import pandas as pd


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "default"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir", nargs="?", default="results")
    args = ap.parse_args()
    root = Path(args.results_dir)

    rows = []
    for path in sorted(root.glob("*/summary.json")):
        data = json.loads(path.read_text())
        data["result_dir"] = path.parent.name
        data["bottleneck_warning_count"] = (
            len(data.get("bottleneck_warnings") or []) + len(data.get("validity_warnings") or [])
        )
        rows.append(data)
    if not rows:
        print("No summary.json files found; nothing to compare.")
        return

    df = pd.DataFrame(rows)
    defaults = {
        "benchmark_engine": "locust",
        "scenario_name": "legacy_unspecified",
        "traffic_path": "legacy_unspecified",
        "generator_network_mode": "legacy_unspecified",
        "estimated_peak_payload_gbps": None,
        "approx_peak_connections_per_second": None,
        "max_sustainable_connections": None,
        "peak_established_connections": None,
        "max_tested_connections": None,
        "peak_connection_establishment_rate_cps": None,
        "max_sustainable_rps": None,
        "max_sustainable_rps_users": None,
        "max_rps_max_tested_users": None,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default
        elif default is not None:
            df[col] = df[col].fillna(default)

    numeric_cols = (
        "peak_rps_history",
        "p99_ms",
        "p95_ms",
        "average_rps",
        "failures",
        "estimated_peak_payload_gbps",
        "approx_peak_connections_per_second",
        "max_sustainable_connections",
        "peak_established_connections",
        "max_tested_connections",
        "peak_connection_establishment_rate_cps",
        "max_sustainable_rps",
        "max_sustainable_rps_users",
        "max_rps_max_tested_users",
    )
    for col in numeric_cols:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df.to_csv(root / "comparison.csv", index=False)

    compatibility_lines = []
    compatibility_warnings = 0
    group_cols = [c for c in ["benchmark_engine", "scenario_name", "traffic_path", "generator_network_mode", "target_kind"] if c in df.columns]
    for keys, group in df.groupby(group_cols, dropna=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        label = ", ".join(f"{col}={value}" for col, value in zip(group_cols, keys))
        fps = sorted({str(x) for x in group.get("spec_fingerprint", pd.Series(dtype=str)).dropna() if str(x)})
        if len(fps) > 1:
            compatibility_warnings += 1
            compatibility_lines.append(f"WARNING {label}: multiple comparison fingerprints: {', '.join(fps)}")
        else:
            compatibility_lines.append(f"OK {label}: fingerprint {fps[0] if fps else 'n/a'}")
    if compatibility_warnings:
        compatibility_lines.insert(0, "One or more scenario populations contain comparison-critical configuration drift. Review RUN_MANIFEST.md before comparing those runs.")
    else:
        compatibility_lines.insert(0, "All runs are fingerprint-compatible within their engine/scenario/traffic-path/generator-topology/target populations.")
    compatibility_text = "\n".join(compatibility_lines) + "\n"
    (root / "comparison-compatibility.txt").write_text(compatibility_text)
    print(compatibility_text, end="")

    octavia = df[df["target_kind"] == "octavia"].copy()
    if not octavia.empty:
        keys = ["benchmark_engine", "scenario_name", "traffic_path", "generator_network_mode", "octavia_flavor"]
        grouped = (
            octavia.groupby(keys, as_index=False, dropna=False)
            .agg(
                runs=("result_dir", "count"),
                median_peak_rps=("peak_rps_history", "median"),
                mean_peak_rps=("peak_rps_history", "mean"),
                std_peak_rps=("peak_rps_history", "std"),
                median_max_sustainable_rps=("max_sustainable_rps", "median"),
                min_max_sustainable_rps=("max_sustainable_rps", "min"),
                max_max_sustainable_rps=("max_sustainable_rps", "max"),
                median_max_sustainable_rps_users=("max_sustainable_rps_users", "median"),
                median_p99_ms=("p99_ms", "median"),
                median_p95_ms=("p95_ms", "median"),
                median_peak_payload_gbps=("estimated_peak_payload_gbps", "median"),
                median_approx_cps=("approx_peak_connections_per_second", "median"),
                median_max_sustainable_connections=("max_sustainable_connections", "median"),
                min_max_sustainable_connections=("max_sustainable_connections", "min"),
                max_max_sustainable_connections=("max_sustainable_connections", "max"),
                median_peak_established_connections=("peak_established_connections", "median"),
                median_connection_establishment_rate_cps=("peak_connection_establishment_rate_cps", "median"),
                total_failures=("failures", "sum"),
                runs_with_resource_warning=("bottleneck_warning_count", lambda s: int((s > 0).sum())),
            )
        )
        grouped.to_csv(root / "comparison-summary.csv", index=False)

        for (engine, scenario_name, traffic_path, generator_network_mode), scenario_group in grouped.groupby(
            ["benchmark_engine", "scenario_name", "traffic_path", "generator_network_mode"], dropna=False
        ):
            label = f"{scenario_name} / {traffic_path} / generators={generator_network_mode}"
            file_label = slug(f"{scenario_name}-{traffic_path}-{generator_network_mode}")

            if engine == "connection_capacity":
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.bar(scenario_group["octavia_flavor"], scenario_group["median_max_sustainable_connections"])
                ax.set_title(f"Concurrent-connection capacity: {label}")
                ax.set_xlabel("Octavia flavor")
                ax.set_ylabel("Median max sustainable simultaneous connections")
                ax.grid(True, axis="y", alpha=0.25)
                fig.tight_layout()
                fig.savefig(root / f"comparison-connections-{file_label}.png", dpi=150)
                plt.close(fig)

                if scenario_group["median_connection_establishment_rate_cps"].notna().any():
                    fig, ax = plt.subplots(figsize=(10, 5))
                    ax.bar(scenario_group["octavia_flavor"], scenario_group["median_connection_establishment_rate_cps"])
                    ax.set_title(f"Capacity-ramp establishment rate: {label}")
                    ax.set_xlabel("Octavia flavor")
                    ax.set_ylabel("Median peak established connections/s")
                    ax.grid(True, axis="y", alpha=0.25)
                    fig.tight_layout()
                    fig.savefig(root / f"comparison-connection-establishment-rate-{file_label}.png", dpi=150)
                    plt.close(fig)
                continue

            if scenario_group["median_max_sustainable_rps"].notna().any():
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.bar(scenario_group["octavia_flavor"], scenario_group["median_max_sustainable_rps"])
                ax.set_title(f"Max sustainable request rate: {label}")
                ax.set_xlabel("Octavia flavor")
                ax.set_ylabel("Median max sustainable requests/s")
                ax.grid(True, axis="y", alpha=0.25)
                fig.tight_layout()
                fig.savefig(root / f"comparison-max-rps-{file_label}.png", dpi=150)
                plt.close(fig)
            elif scenario_group["median_peak_rps"].notna().any():
                fig, ax = plt.subplots(figsize=(10, 5))
                yerr = scenario_group["std_peak_rps"].fillna(0)
                ax.bar(scenario_group["octavia_flavor"], scenario_group["median_peak_rps"], yerr=yerr, capsize=4)
                ax.set_title(f"Request-rate comparison: {label}")
                ax.set_xlabel("Octavia flavor")
                ax.set_ylabel("Median peak requests/s (error bar: run std dev)")
                ax.grid(True, axis="y", alpha=0.25)
                fig.tight_layout()
                fig.savefig(root / f"comparison-rps-{file_label}.png", dpi=150)
                plt.close(fig)

            if scenario_group["median_p99_ms"].notna().any():
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.bar(scenario_group["octavia_flavor"], scenario_group["median_p99_ms"])
                ax.set_title(f"p99 latency comparison: {label}")
                ax.set_xlabel("Octavia flavor")
                ax.set_ylabel("Median run p99 latency (ms)")
                ax.grid(True, axis="y", alpha=0.25)
                fig.tight_layout()
                fig.savefig(root / f"comparison-p99-{file_label}.png", dpi=150)
                plt.close(fig)

            if scenario_group["median_peak_payload_gbps"].notna().any():
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.bar(scenario_group["octavia_flavor"], scenario_group["median_peak_payload_gbps"])
                ax.set_title(f"Payload-throughput comparison: {label}")
                ax.set_xlabel("Octavia flavor")
                ax.set_ylabel("Median peak application payload Gb/s")
                ax.grid(True, axis="y", alpha=0.25)
                fig.tight_layout()
                fig.savefig(root / f"comparison-throughput-{file_label}.png", dpi=150)
                plt.close(fig)

    print(root / "comparison.csv")


if __name__ == "__main__":
    main()
