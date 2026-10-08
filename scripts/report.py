#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
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
