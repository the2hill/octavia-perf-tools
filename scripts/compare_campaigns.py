#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-") or "default"


def as_number(value: Any) -> float:
    try:
        if value is None or value == "":
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def iso_sort_value(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text else fallback


def primary_metric(row: pd.Series) -> tuple[str, str, float]:
    engine = str(row.get("benchmark_engine") or "locust")
    profile = str(row.get("locust_profile") or "staircase")
    connection_mode = str(row.get("connection_mode") or "keepalive")
    payload = as_number(row.get("payload_bytes"))

    if engine == "connection_capacity":
        return (
            "max_sustainable_connections",
            "simultaneous connections",
            as_number(row.get("max_sustainable_connections")),
        )
    if profile == "max_rps":
        return (
            "max_sustainable_rps",
            "requests/s",
            as_number(row.get("max_sustainable_rps")),
        )
    if connection_mode == "close":
        return (
            "approx_peak_connections_per_second",
            "connections/s",
            as_number(row.get("approx_peak_connections_per_second")),
        )
    if not math.isnan(payload) and payload >= 65536:
        return (
            "estimated_peak_payload_gbps",
            "Gb/s payload",
            as_number(row.get("estimated_peak_payload_gbps")),
        )
    return ("peak_rps_history", "requests/s", as_number(row.get("peak_rps_history")))


def p99_value(row: pd.Series) -> float:
    if str(row.get("locust_profile") or "") == "max_rps":
        value = as_number(row.get("max_rps_best_p99_ms"))
        if not math.isnan(value):
            return value
    return as_number(row.get("p99_ms"))


def failure_percent(row: pd.Series) -> float:
    if str(row.get("locust_profile") or "") == "max_rps":
        value = as_number(row.get("max_rps_best_failure_percent"))
        if not math.isnan(value):
            return value
    failures = as_number(row.get("failures"))
    requests = as_number(row.get("requests"))
    if math.isnan(failures) or math.isnan(requests) or requests <= 0:
        return math.nan
    return failures / requests * 100.0


def fmt(value: Any, digits: int = 1) -> str:
    value = as_number(value)
    if math.isnan(value):
        return "—"
    if abs(value) >= 1000000:
        return f"{value / 1000000:.2f}M"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.{digits}f}"


def fmt_pct(value: Any, digits: int = 1) -> str:
    value = as_number(value)
    return "—" if math.isnan(value) else f"{value:.{digits}f}%"


def md_table(frame: pd.DataFrame, columns: list[str], headers: list[str] | None = None) -> str:
    if frame.empty:
        return "_No data._\n"
    headers = headers or columns
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in frame.iterrows():
        vals = []
        for col in columns:
            value = row.get(col, "")
            text = "" if pd.isna(value) else str(value)
            vals.append(text.replace("|", "\\|"))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def save_bar(frame: pd.DataFrame, x: str, y: str, title: str, ylabel: str, path: Path, horizontal: bool = False) -> None:
    if frame.empty or frame[y].dropna().empty:
        return
    fig, ax = plt.subplots(figsize=(10, max(5, 0.5 * len(frame) + 2) if horizontal else 5))
    if horizontal:
        ax.barh(frame[x], frame[y])
        ax.set_xlabel(ylabel)
        ax.set_ylabel("")
        ax.invert_yaxis()
    else:
        ax.bar(frame[x], frame[y])
        ax.set_ylabel(ylabel)
        ax.set_xlabel("")
        ax.tick_params(axis="x", rotation=25)
    ax.set_title(title)
    ax.grid(True, axis="x" if horizontal else "y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def draw_heatmap_on_ax(
    ax: plt.Axes,
    pivot: pd.DataFrame,
    title: str,
    *,
    suffix: str = "",
    vmin: float = 0,
    vmax: float = 100,
    value_label: str = "Index (100 = best in scenario)",
    annotate: bool = True,
) -> Any:
    values = pivot.to_numpy(dtype=float)
    masked = np.ma.masked_invalid(values)
    image = ax.imshow(masked, aspect="auto", vmin=vmin, vmax=vmax)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=25, ha="right")
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_title(title, fontweight="bold")
    if annotate:
        for i in range(values.shape[0]):
            for j in range(values.shape[1]):
                value = values[i, j]
                if not math.isnan(value):
                    ax.text(j, i, f"{value:.0f}{suffix}", ha="center", va="center", fontsize=8)
    image._octavia_value_label = value_label  # type: ignore[attr-defined]
    return image


def save_heatmap(pivot: pd.DataFrame, title: str, path: Path, suffix: str = "") -> None:
    if pivot.empty:
        return
    fig_width = max(8, 1.8 * len(pivot.columns) + 3)
    fig_height = max(5, 0.58 * len(pivot.index) + 2.5)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    image = draw_heatmap_on_ax(ax, pivot, title, suffix=suffix)
    fig.colorbar(image, ax=ax, label="Index (100 = best in scenario)")
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def draw_horizontal_bar(
    ax: plt.Axes,
    frame: pd.DataFrame,
    label_col: str,
    value_col: str,
    title: str,
    xlabel: str,
    *,
    value_suffix: str = "",
    digits: int = 0,
) -> None:
    usable = frame[[label_col, value_col]].dropna().copy()
    if usable.empty:
        ax.axis("off")
        ax.text(0.5, 0.5, "No comparable data", ha="center", va="center", transform=ax.transAxes)
        return
    y = np.arange(len(usable))
    values = usable[value_col].astype(float).to_numpy()
    ax.barh(y, values)
    ax.set_yticks(y)
    ax.set_yticklabels(usable[label_col].astype(str))
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    ax.set_title(title, fontweight="bold")
    ax.grid(True, axis="x", alpha=0.25)
    pad = max(np.nanmax(np.abs(values)) * 0.015, 0.5)
    for yi, value in zip(y, values):
        ax.text(value + pad, yi, f"{value:.{digits}f}{value_suffix}", va="center", fontsize=9)


def make_composite_dashboard(
    path: Path,
    summary: pd.DataFrame,
    scorecard: pd.DataFrame,
) -> None:
    if summary.empty or scorecard.empty:
        return

    scenario_label = summary.apply(
        lambda r: f"{r['scenario_name']}\n{r['traffic_path']} / {r['generator_network_mode']}", axis=1
    )
    labeled = summary.assign(scenario_label=scenario_label)
    perf_heat = labeled.pivot_table(
        index="scenario_label", columns="octavia_flavor", values="performance_index", aggfunc="first"
    )
    latency_heat = labeled.pivot_table(
        index="scenario_label", columns="octavia_flavor", values="latency_index", aggfunc="first"
    )

    ordered_flavors = scorecard.sort_values(
        ["median_performance_index", "median_latency_index"], ascending=[False, False]
    )["octavia_flavor"].astype(str).tolist()
    perf_heat = perf_heat.reindex(columns=[x for x in ordered_flavors if x in perf_heat.columns])
    latency_heat = latency_heat.reindex(columns=[x for x in ordered_flavors if x in latency_heat.columns])

    fig_height = max(16, 8 + 0.75 * max(len(perf_heat.index), len(latency_heat.index)))
    fig = plt.figure(figsize=(18, fig_height))
    grid = fig.add_gridspec(
        4, 2,
        height_ratios=[1.0, max(1.8, 0.26 * len(perf_heat.index) + 1.0),
                       max(1.6, 0.26 * len(latency_heat.index) + 1.0), 1.0],
        hspace=0.65, wspace=0.35,
    )

    best_flavor = str(scorecard.iloc[0]["octavia_flavor"])
    population_count = summary[["scenario_name", "traffic_path", "generator_network_mode"]].drop_duplicates().shape[0]
    warning_count = summary.loc[
        summary["population_fingerprint_count"] > 1,
        ["scenario_name", "traffic_path", "generator_network_mode"],
    ].drop_duplicates().shape[0]
    subtitle = (
        f"{len(scorecard)} flavors | {population_count} comparable scenario populations | "
        f"overall leader: {best_flavor} | fingerprint warnings: {warning_count}"
    )
    fig.suptitle("Octavia Flavor Performance Comparison", fontsize=20, fontweight="bold", y=0.995)
    fig.text(0.5, 0.973, subtitle, ha="center", va="top", fontsize=10)

    overall = scorecard.sort_values("median_performance_index", ascending=False)
    ax = fig.add_subplot(grid[0, 0])
    draw_horizontal_bar(
        ax, overall, "octavia_flavor", "median_performance_index",
        "Overall performance index", "Median scenario-relative index (100 = best)",
    )
    ax.set_xlim(left=0)

    wins = scorecard.sort_values(["scenario_wins", "median_performance_index"], ascending=[False, False])
    ax = fig.add_subplot(grid[0, 1])
    draw_horizontal_bar(
        ax, wins, "octavia_flavor", "scenario_wins",
        "Scenario wins", "Scenario populations won",
    )
    ax.set_xlim(left=0)

    ax = fig.add_subplot(grid[1, :])
    if not perf_heat.empty:
        image = draw_heatmap_on_ax(ax, perf_heat, "Performance by scenario")
        fig.colorbar(image, ax=ax, fraction=0.018, pad=0.015, label="Performance index (100 = best)")
    else:
        ax.axis("off")

    ax = fig.add_subplot(grid[2, :])
    if not latency_heat.empty and latency_heat.notna().any().any():
        image = draw_heatmap_on_ax(ax, latency_heat, "p99 latency by scenario")
        fig.colorbar(image, ax=ax, fraction=0.018, pad=0.015, label="Latency index (100 = lowest p99)")
    else:
        ax.axis("off")
        ax.text(0.5, 0.5, "No comparable p99 latency data", ha="center", va="center", transform=ax.transAxes)

    variability = scorecard.sort_values("median_run_cv_percent", ascending=True)
    ax = fig.add_subplot(grid[3, 0])
    draw_horizontal_bar(
        ax, variability, "octavia_flavor", "median_run_cv_percent",
        "Run-to-run variability", "Median CV (%) — lower is better",
        value_suffix="%", digits=1,
    )
    ax.set_xlim(left=0)

    direct = (
        summary.dropna(subset=["percent_of_direct"])
        .groupby("octavia_flavor", as_index=False)["percent_of_direct"]
        .median()
        .sort_values("percent_of_direct", ascending=False)
    )
    ax = fig.add_subplot(grid[3, 1])
    if not direct.empty:
        draw_horizontal_bar(
            ax, direct, "octavia_flavor", "percent_of_direct",
            "Efficiency vs direct nginx", "Median Octavia throughput as % of matching direct control",
            value_suffix="%", digits=1,
        )
        ax.set_xlim(left=0)
    else:
        ax.axis("off")
        ax.text(
            0.5, 0.5,
            "No flavor-scoped direct controls available\nfor Octavia/direct efficiency",
            ha="center", va="center", transform=ax.transAxes,
        )
        ax.set_title("Efficiency vs direct nginx", fontweight="bold")

    fig.text(
        0.5, 0.008,
        "Normalized indexes compare flavors only within the same scenario/path/topology. "
        "See DETAILED_COMPARISON.md for native RPS/CPS/Gb/s/connection values and source runs.",
        ha="center", va="bottom", fontsize=9,
    )
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def load_results(root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/summary.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARNING: skipping unreadable {path}: {exc}")
            continue
        data["result_dir"] = path.parent.name
        data["summary_path"] = str(path)
        data["sort_time"] = iso_sort_value(data.get("load_test_started_at_utc"), path.parent.name)
        rows.append(data)
    return pd.DataFrame(rows)


def choose_latest(df: pd.DataFrame, group_cols: list[str], count: int) -> pd.DataFrame:
    if df.empty or count <= 0:
        return df.copy()
    pieces = []
    for _, group in df.groupby(group_cols, dropna=False):
        pieces.append(group.sort_values(["sort_time", "result_dir"]).tail(count))
    return pd.concat(pieces, ignore_index=True) if pieces else df.iloc[0:0].copy()


def aggregate_octavia(selected: pd.DataFrame) -> pd.DataFrame:
    if selected.empty:
        return pd.DataFrame()
    rows = []
    group_cols = ["scenario_name", "traffic_path", "generator_network_mode", "octavia_flavor"]
    for keys, group in selected.groupby(group_cols, dropna=False):
        scenario, traffic_path, generator_mode, flavor = keys
        metric_names = [x for x in group["primary_metric"].dropna().unique()]
        units = [x for x in group["primary_unit"].dropna().unique()]
        primary = pd.to_numeric(group["primary_value"], errors="coerce")
        p99 = pd.to_numeric(group["p99_effective_ms"], errors="coerce")
        failure = pd.to_numeric(group["failure_percent_effective"], errors="coerce")
        requests = pd.to_numeric(group.get("requests", pd.Series(index=group.index, dtype=float)), errors="coerce")
        failures = pd.to_numeric(group.get("failures", pd.Series(index=group.index, dtype=float)), errors="coerce")
        amphora_peak_cpu_cores = pd.to_numeric(group.get("amphora_peak_cpu_cores", pd.Series(index=group.index, dtype=float)), errors="coerce")
        amphora_peak_cpu_percent = pd.to_numeric(group.get("amphora_peak_cpu_percent", pd.Series(index=group.index, dtype=float)), errors="coerce")
        amphora_hottest_vcpu_percent = pd.to_numeric(group.get("amphora_hottest_vcpu_percent", pd.Series(index=group.index, dtype=float)), errors="coerce")
        amphora_peak_tx_pps = pd.to_numeric(group.get("amphora_peak_tx_packets_per_second", pd.Series(index=group.index, dtype=float)), errors="coerce")
        amphora_peak_rx_pps = pd.to_numeric(group.get("amphora_peak_rx_packets_per_second", pd.Series(index=group.index, dtype=float)), errors="coerce")
        amphora_peak_vcpu_delay = pd.to_numeric(group.get("amphora_peak_vcpu_delay_seconds_per_second", pd.Series(index=group.index, dtype=float)), errors="coerce")
        amphora_peak_vcpu_wait = pd.to_numeric(group.get("amphora_peak_vcpu_wait_seconds_per_second", pd.Series(index=group.index, dtype=float)), errors="coerce")
        med = primary.median()
        std = primary.std(ddof=1)
        cv = (std / med * 100.0) if pd.notna(std) and pd.notna(med) and med != 0 else math.nan
        fps = sorted({str(x) for x in group.get("spec_fingerprint", pd.Series(dtype=str)).dropna() if str(x)})
        rows.append(
            {
                "scenario_name": scenario,
                "traffic_path": traffic_path,
                "generator_network_mode": generator_mode,
                "octavia_flavor": flavor,
                "runs": len(group),
                "primary_metric": metric_names[0] if len(metric_names) == 1 else ",".join(sorted(metric_names)),
                "primary_unit": units[0] if len(units) == 1 else ",".join(sorted(units)),
                "median_primary": med,
                "min_primary": primary.min(),
                "max_primary": primary.max(),
                "mean_primary": primary.mean(),
                "std_primary": std,
                "cv_percent": cv,
                "median_p99_ms": p99.median(),
                "min_p99_ms": p99.min(),
                "max_p99_ms": p99.max(),
                "median_failure_percent": failure.median(),
                "median_amphora_peak_cpu_cores": amphora_peak_cpu_cores.median(),
                "median_amphora_peak_cpu_percent": amphora_peak_cpu_percent.median(),
                "median_amphora_hottest_vcpu_percent": amphora_hottest_vcpu_percent.median(),
                "median_amphora_peak_tx_pps": amphora_peak_tx_pps.median(),
                "median_amphora_peak_rx_pps": amphora_peak_rx_pps.median(),
                "median_amphora_peak_vcpu_delay": amphora_peak_vcpu_delay.median(),
                "median_amphora_peak_vcpu_wait": amphora_peak_vcpu_wait.median(),
                "total_requests": requests.sum(min_count=1),
                "total_failures": failures.sum(min_count=1),
                "fingerprint_count": len(fps),
                "fingerprints": ",".join(fps),
                "first_test_utc": group["sort_time"].min(),
                "last_test_utc": group["sort_time"].max(),
            }
        )
    return pd.DataFrame(rows)


def add_relative_metrics(summary: pd.DataFrame, reference_flavor: str | None) -> pd.DataFrame:
    if summary.empty:
        return summary
    summary = summary.copy()
    population_cols = ["scenario_name", "traffic_path", "generator_network_mode"]
    summary["performance_index"] = math.nan
    summary["latency_index"] = math.nan
    summary["delta_vs_best_percent"] = math.nan
    summary["delta_vs_reference_percent"] = math.nan
    summary["p99_delta_vs_reference_percent"] = math.nan

    for _, group in summary.groupby(population_cols, dropna=False):
        valid = group["median_primary"].dropna()
        if not valid.empty and valid.max() > 0:
            best = valid.max()
            summary.loc[group.index, "performance_index"] = group["median_primary"] / best * 100.0
            summary.loc[group.index, "delta_vs_best_percent"] = (group["median_primary"] / best - 1.0) * 100.0
        p99_valid = group["median_p99_ms"].dropna()
        if not p99_valid.empty and p99_valid.min() > 0:
            best_latency = p99_valid.min()
            summary.loc[group.index, "latency_index"] = best_latency / group["median_p99_ms"] * 100.0
        if reference_flavor:
            ref = group[group["octavia_flavor"] == reference_flavor]
            if not ref.empty:
                ref_primary = as_number(ref.iloc[0]["median_primary"])
                ref_p99 = as_number(ref.iloc[0]["median_p99_ms"])
                if not math.isnan(ref_primary) and ref_primary != 0:
                    summary.loc[group.index, "delta_vs_reference_percent"] = (
                        group["median_primary"] / ref_primary - 1.0
                    ) * 100.0
                if not math.isnan(ref_p99) and ref_p99 != 0:
                    summary.loc[group.index, "p99_delta_vs_reference_percent"] = (
                        group["median_p99_ms"] / ref_p99 - 1.0
                    ) * 100.0
    return summary


def aggregate_direct(direct: pd.DataFrame, latest_direct: int) -> pd.DataFrame:
    if direct.empty:
        return pd.DataFrame()
    # Direct controls are independent of Octavia, but baseline_for_flavor is a
    # provenance tag tying each control to the one-flavor suite that collected
    # it. New results are therefore compared to the matching suite control.
    # Older untagged controls remain visible as legacy_unscoped and are never
    # silently assigned to a flavor.
    group_cols = ["scenario_name", "generator_network_mode", "baseline_for_flavor"]
    direct = choose_latest(direct, group_cols, latest_direct)
    rows = []
    for keys, group in direct.groupby(group_cols, dropna=False):
        scenario, generator, baseline_for = keys
        primary = pd.to_numeric(group["primary_value"], errors="coerce")
        rows.append(
            {
                "scenario_name": scenario,
                "generator_network_mode": generator,
                "baseline_for_flavor": baseline_for,
                "direct_traffic_path": ",".join(sorted({str(x) for x in group["traffic_path"].dropna()})),
                "direct_runs": len(group),
                "direct_metric": group["primary_metric"].dropna().iloc[0] if group["primary_metric"].notna().any() else "",
                "direct_unit": group["primary_unit"].dropna().iloc[0] if group["primary_unit"].notna().any() else "",
                "direct_median_primary": primary.median(),
                "direct_median_p99_ms": pd.to_numeric(group["p99_effective_ms"], errors="coerce").median(),
                "direct_suite_ids": ",".join(sorted({str(x) for x in group["suite_id"].dropna() if str(x)})),
            }
        )
    return pd.DataFrame(rows)


def flavor_scorecard(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    rows = []
    for flavor, group in summary.groupby("octavia_flavor", dropna=False):
        perf = pd.to_numeric(group["performance_index"], errors="coerce")
        latency = pd.to_numeric(group["latency_index"], errors="coerce")
        cv = pd.to_numeric(group["cv_percent"], errors="coerce")
        failure = pd.to_numeric(group["median_failure_percent"], errors="coerce")
        wins = int((perf >= 99.999).sum())
        rows.append(
            {
                "octavia_flavor": flavor,
                "scenario_coverage": int(perf.notna().sum()),
                "scenario_wins": wins,
                "median_performance_index": perf.median(),
                "mean_performance_index": perf.mean(),
                "worst_performance_index": perf.min(),
                "median_latency_index": latency.median(),
                "median_run_cv_percent": cv.median(),
                "max_run_cv_percent": cv.max(),
                "median_failure_percent": failure.median(),
                "warning_groups": int((group["population_fingerprint_count"] > 1).sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["median_performance_index", "median_latency_index"], ascending=[False, False]
    )



def scenario_winners(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    rows = []
    for keys, group in summary.groupby(["scenario_name", "traffic_path", "generator_network_mode"], dropna=False):
        scenario, path, generator = keys
        valid = group.dropna(subset=["median_primary"]).sort_values("median_primary", ascending=False)
        if valid.empty:
            continue
        best_value = as_number(valid.iloc[0]["median_primary"])
        winners = valid[np.isclose(valid["median_primary"].astype(float), best_value, rtol=1e-12, atol=1e-12)]
        second = valid.iloc[len(winners):len(winners)+1]
        second_value = as_number(second.iloc[0]["median_primary"]) if not second.empty else math.nan
        margin = ((best_value / second_value) - 1.0) * 100.0 if not math.isnan(second_value) and second_value != 0 else math.nan
        rows.append({
            "scenario_name": scenario,
            "traffic_path": path,
            "generator_network_mode": generator,
            "primary_metric": valid.iloc[0]["primary_metric"],
            "primary_unit": valid.iloc[0]["primary_unit"],
            "winner_flavor": ", ".join(str(x) for x in winners["octavia_flavor"].tolist()),
            "winner_value": best_value,
            "runner_up_flavor": str(second.iloc[0]["octavia_flavor"]) if not second.empty else "",
            "runner_up_value": second_value,
            "winner_margin_percent": margin,
            "population_fingerprint_count": int(valid.iloc[0]["population_fingerprint_count"]),
        })
    return pd.DataFrame(rows)

def write_reports(
    out: Path,
    selected: pd.DataFrame,
    summary: pd.DataFrame,
    direct_summary: pd.DataFrame,
    scorecard: pd.DataFrame,
    winners: pd.DataFrame,
    reference_flavor: str | None,
    latest_per_group: int,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    selected.to_csv(out / "selected-runs.csv", index=False)
    summary.to_csv(out / "scenario-summary.csv", index=False)
    scorecard.to_csv(out / "flavor-scorecard.csv", index=False)
    winners.to_csv(out / "scenario-winners.csv", index=False)
    if not direct_summary.empty:
        direct_summary.to_csv(out / "direct-reference-summary.csv", index=False)

    flavor_names = [str(x) for x in scorecard["octavia_flavor"].tolist()] if not scorecard.empty else []
    scenario_count = summary[["scenario_name", "traffic_path", "generator_network_mode"]].drop_duplicates().shape[0]
    compatibility_groups = int((summary["population_fingerprint_count"] > 1).sum()) if not summary.empty else 0

    exec_rows = scorecard.copy()
    if not exec_rows.empty:
        exec_rows["median_performance_index"] = exec_rows["median_performance_index"].map(lambda x: fmt_pct(x))
        exec_rows["median_latency_index"] = exec_rows["median_latency_index"].map(lambda x: fmt_pct(x))
        exec_rows["median_run_cv_percent"] = exec_rows["median_run_cv_percent"].map(lambda x: fmt_pct(x))
        exec_rows["median_failure_percent"] = exec_rows["median_failure_percent"].map(lambda x: fmt_pct(x, 3))

    reference_text = f" Relative deltas also use **{reference_flavor}** as the reference flavor." if reference_flavor else ""
    selection_text = (
        f"The report uses the latest **{latest_per_group}** successful runs per flavor/scenario/path/topology group."
        if latest_per_group > 0
        else "The report uses every matching successful run under the results directory."
    )

    executive = f"""# Octavia Flavor Campaign Comparison

## At a glance

This report combines independently executed baseline-suite runs from the same `results/` tree. {selection_text}{reference_text}

- Octavia flavors compared: **{len(flavor_names)}** ({', '.join(flavor_names) if flavor_names else 'none'})
- Comparable scenario/path/topology populations: **{scenario_count}**
- Selected Octavia run samples: **{len(selected)}**
- Populations with multiple comparison fingerprints: **{compatibility_groups}**

### Simple scorecard

`Performance index` normalizes the primary throughput/capacity metric inside each scenario so the best flavor is 100. It is then summarized across scenarios using the median. This is a comparative index, **not** a synthetic requests-per-second number. `Latency index` similarly gives 100 to the lowest p99 latency within a scenario. Higher is better for both indexes. Lower run CV is more consistent.

{md_table(exec_rows, ['octavia_flavor','scenario_wins','scenario_coverage','median_performance_index','median_latency_index','median_run_cv_percent','median_failure_percent'], ['Flavor','Scenario wins','Coverage','Median performance index','Median latency index','Median run CV','Median failure %'])}

## Charts

### Composite dashboard

This is the single-image overview intended for quick review, sharing, or presentation use. It combines overall flavor performance, scenario wins, per-scenario performance and p99 latency indexes, run variability, and flavor-scoped direct-nginx efficiency where available.

![Composite dashboard](charts/composite-dashboard.png)

### Individual charts

![Overall performance index](charts/flavor-overall-performance-index.png)

![Scenario performance matrix](charts/scenario-performance-index.png)

![Scenario p99 latency matrix](charts/scenario-latency-index.png)

![Scenario wins](charts/scenario-wins.png)

![Run-to-run variability](charts/flavor-variability.png)

## Reading this report

- Use **scenario wins** and the performance heatmap to see where each flavor is strongest.
- Use the **median performance index** for a compact cross-scenario view, but use the detailed tables for purchasing/product decisions because scenarios have different units and workload semantics.
- Use **run CV** to spot noisy or unstable results. With only three repetitions, treat very small differences as directional rather than statistically definitive.
- Any fingerprint warning means the harness detected comparison-critical configuration/software drift. Review those populations before drawing conclusions.

See [`DETAILED_COMPARISON.md`](DETAILED_COMPARISON.md) for actual metric values, ranges, p99 latency, failure rates, deltas, and direct-nginx references.
"""
    if not winners.empty:
        winner_display = winners.copy()
        winner_display["winner_value"] = winner_display["winner_value"].map(fmt)
        winner_display["winner_margin_percent"] = winner_display["winner_margin_percent"].map(fmt_pct)
        winner_table = md_table(
            winner_display,
            ["scenario_name", "winner_flavor", "winner_value", "primary_unit", "runner_up_flavor", "winner_margin_percent"],
            ["Scenario", "Winner", "Winning value", "Unit", "Runner-up", "Margin"],
        )
        executive += "\n## Winner by scenario\n\n" + winner_table

    compatibility_lines = []
    for keys, group in summary.groupby(["scenario_name", "traffic_path", "generator_network_mode"], dropna=False):
        scenario, path, generator = keys
        count = int(group.iloc[0]["population_fingerprint_count"])
        fps = str(group.iloc[0]["population_fingerprints"] or "")
        status = "OK" if count <= 1 else "WARNING"
        compatibility_lines.append(f"{status} scenario={scenario}, traffic_path={path}, generators={generator}: fingerprints={fps or 'n/a'}")
    (out / "comparison-compatibility.txt").write_text("\n".join(compatibility_lines) + "\n")

    (out / "README.md").write_text(executive)

    detail_lines = [
        "# Detailed Octavia Flavor Comparison",
        "",
        "Each table below is one comparable scenario/path/generator-topology population. The primary metric is chosen from the scenario semantics: max sustainable RPS for adaptive max-RPS tests, approximate connections/s for connection-churn tests, simultaneous connections for capacity tests, payload Gb/s for large-payload bandwidth tests, and peak RPS for ordinary keepalive tests.",
        "",
    ]

    population_cols = ["scenario_name", "traffic_path", "generator_network_mode"]
    for keys, group in summary.groupby(population_cols, dropna=False):
        scenario, path, generator = keys
        group = group.sort_values("median_primary", ascending=False).copy()
        unit = str(group["primary_unit"].dropna().iloc[0]) if group["primary_unit"].notna().any() else "metric"
        metric = str(group["primary_metric"].dropna().iloc[0]) if group["primary_metric"].notna().any() else "primary metric"
        detail_lines.extend(
            [
                f"## {scenario}",
                "",
                f"Traffic path: `{path}`  ",
                f"Generator topology: `{generator}`  ",
                f"Primary metric: `{metric}` ({unit})",
                "",
            ]
        )
        display = pd.DataFrame(
            {
                "Flavor": group["octavia_flavor"].astype(str),
                "Runs": group["runs"].astype(int).astype(str),
                "Median": group["median_primary"].map(fmt),
                "Min": group["min_primary"].map(fmt),
                "Max": group["max_primary"].map(fmt),
                "Run CV": group["cv_percent"].map(fmt_pct),
                "vs best": group["delta_vs_best_percent"].map(lambda x: fmt_pct(x)),
                "p99 ms": group["median_p99_ms"].map(fmt),
                "Failure %": group["median_failure_percent"].map(lambda x: fmt_pct(x, 3)),
                "Fingerprints": group["population_fingerprint_count"].astype(int).astype(str),
            }
        )
        if reference_flavor:
            display.insert(7, f"vs {reference_flavor}", group["delta_vs_reference_percent"].map(fmt_pct))
        if group["median_amphora_peak_cpu_cores"].notna().any():
            display["Amph peak cores"] = group["median_amphora_peak_cpu_cores"].map(lambda x: fmt(x, 2))
        if group["median_amphora_hottest_vcpu_percent"].notna().any():
            display["Hot vCPU %"] = group["median_amphora_hottest_vcpu_percent"].map(lambda x: fmt_pct(x, 1))
        if group["median_amphora_peak_tx_pps"].notna().any():
            display["Peak TX pps"] = group["median_amphora_peak_tx_pps"].map(fmt)
        if group["median_amphora_peak_vcpu_delay"].notna().any():
            display["vCPU delay s/s"] = group["median_amphora_peak_vcpu_delay"].map(lambda x: fmt(x, 6))
        detail_lines.append(md_table(display, list(display.columns)))

        if not direct_summary.empty:
            match = direct_summary[
                (direct_summary["scenario_name"] == scenario)
                & (direct_summary["generator_network_mode"] == generator)
            ].copy()
            if not match.empty:
                detail_lines.append("### Direct nginx control provenance")
                detail_lines.append("")
                direct_rows = []
                for _, d in match.sort_values("baseline_for_flavor").iterrows():
                    direct_rows.append({
                        "Suite flavor": d["baseline_for_flavor"],
                        "Runs": int(d["direct_runs"]),
                        "Median": fmt(d["direct_median_primary"]),
                        "Unit": d["direct_unit"],
                        "Suite IDs": d.get("direct_suite_ids", ""),
                    })
                detail_lines.append(md_table(pd.DataFrame(direct_rows), ["Suite flavor", "Runs", "Median", "Unit", "Suite IDs"]))
                legacy = match[match["baseline_for_flavor"] == "legacy_unscoped"]
                if not legacy.empty:
                    detail_lines.append(
                        "**Legacy direct-control warning:** these older results predate suite-flavor provenance tagging. "
                        "They are shown for context but are not used for flavor-specific Octavia-to-direct ratios."
                    )
                    detail_lines.append("")
                ratios = []
                for _, row in group.iterrows():
                    direct_value = as_number(row.get("direct_median_primary"))
                    value = as_number(row["median_primary"])
                    if not math.isnan(value) and not math.isnan(direct_value) and direct_value > 0:
                        ratios.append(f"{row['octavia_flavor']}: {value / direct_value * 100:.1f}% of its suite direct control")
                if ratios:
                    detail_lines.append("Octavia-to-direct ratio: " + "; ".join(ratios) + ".")
                    detail_lines.append("")

        incompatible = group[group["population_fingerprint_count"] > 1]
        if not incompatible.empty:
            detail_lines.append("**Compatibility warning:** one or more flavor groups contain multiple fingerprints. Review `selected-runs.csv` and the original `RUN_MANIFEST.md` files before treating this population as controlled.")
            detail_lines.append("")

    detail_lines.extend(
        [
            "## Selected source runs",
            "",
            "The exact source directories used for this report are listed in `selected-runs.csv`. This makes the report reproducible even when older benchmark history remains under `results/`.",
            "",
        ]
    )
    (out / "DETAILED_COMPARISON.md").write_text("\n".join(detail_lines) + "\n")


def make_charts(out: Path, summary: pd.DataFrame, scorecard: pd.DataFrame) -> None:
    charts = out / "charts"
    charts.mkdir(parents=True, exist_ok=True)

    make_composite_dashboard(charts / "composite-dashboard.png", summary, scorecard)

    if not scorecard.empty:
        save_bar(
            scorecard.sort_values("median_performance_index", ascending=False),
            "octavia_flavor",
            "median_performance_index",
            "Overall cross-scenario performance index",
            "Median scenario-relative index (100 = best)",
            charts / "flavor-overall-performance-index.png",
        )
        save_bar(
            scorecard.sort_values("scenario_wins", ascending=False),
            "octavia_flavor",
            "scenario_wins",
            "Scenario wins by flavor",
            "Number of scenario populations won",
            charts / "scenario-wins.png",
        )
        save_bar(
            scorecard.sort_values("median_run_cv_percent", ascending=True),
            "octavia_flavor",
            "median_run_cv_percent",
            "Run-to-run variability",
            "Median coefficient of variation (%) — lower is better",
            charts / "flavor-variability.png",
        )

    if not summary.empty:
        scenario_label = summary.apply(
            lambda r: f"{r['scenario_name']}\n{r['traffic_path']} / {r['generator_network_mode']}", axis=1
        )
        heat = summary.assign(scenario_label=scenario_label).pivot_table(
            index="scenario_label", columns="octavia_flavor", values="performance_index", aggfunc="first"
        )
        save_heatmap(heat, "Scenario-relative performance index", charts / "scenario-performance-index.png")

        latency_heat = summary.assign(scenario_label=scenario_label).pivot_table(
            index="scenario_label", columns="octavia_flavor", values="latency_index", aggfunc="first"
        )
        if not latency_heat.empty and latency_heat.notna().any().any():
            save_heatmap(latency_heat, "Scenario-relative p99 latency index", charts / "scenario-latency-index.png")

        for keys, group in summary.groupby(["scenario_name", "traffic_path", "generator_network_mode"], dropna=False):
            scenario, path, generator = keys
            unit = str(group["primary_unit"].dropna().iloc[0]) if group["primary_unit"].notna().any() else "metric"
            chart_data = group.sort_values("median_primary", ascending=False)
            save_bar(
                chart_data,
                "octavia_flavor",
                "median_primary",
                f"{scenario}: primary performance",
                f"Median {unit}",
                charts / f"actual-{slug(scenario)}-{slug(path)}-{slug(generator)}.png",
            )
            if group["median_p99_ms"].notna().any():
                save_bar(
                    group.sort_values("median_p99_ms", ascending=True),
                    "octavia_flavor",
                    "median_p99_ms",
                    f"{scenario}: p99 latency",
                    "Median p99 latency (ms) — lower is better",
                    charts / f"p99-{slug(scenario)}-{slug(path)}-{slug(generator)}.png",
                )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Combine independently executed Octavia baseline suites into one cross-flavor report."
    )
    ap.add_argument("results_dir", nargs="?", default="results")
    ap.add_argument("--output", help="Output directory (default: <results>/campaign-comparison)")
    ap.add_argument("--flavor", action="append", default=[], help="Include only this Octavia flavor; repeatable")
    ap.add_argument("--scenario", action="append", default=[], help="Include only this scenario; repeatable")
    ap.add_argument(
        "--latest-per-group",
        type=int,
        default=3,
        help="Use latest N successful Octavia runs per flavor/scenario/path/topology (default: 3; 0 = all)",
    )
    ap.add_argument(
        "--latest-direct",
        type=int,
        default=4,
        help="Use latest N direct nginx runs per scenario/path/topology for reference (default: 4; 0 = all)",
    )
    ap.add_argument("--reference-flavor", help="Show deltas relative to this flavor as well as the per-scenario best")
    ap.add_argument(
        "--strict-fingerprint",
        action="store_true",
        help="Exit non-zero if a compared scenario population contains more than one comparison fingerprint",
    )
    args = ap.parse_args()

    if args.latest_per_group < 0 or args.latest_direct < 0:
        raise SystemExit("latest counts must be >= 0")

    root = Path(args.results_dir).resolve()
    out = Path(args.output).resolve() if args.output else root / "campaign-comparison"
    df = load_results(root)
    if df.empty:
        raise SystemExit(f"No summary.json files found under {root}")

    defaults = {
        "target_kind": "unknown",
        "benchmark_engine": "locust",
        "locust_profile": "staircase",
        "scenario_name": "legacy_unspecified",
        "traffic_path": "legacy_unspecified",
        "generator_network_mode": "legacy_unspecified",
        "octavia_flavor": "unknown",
        "suite_id": "",
        "baseline_for_flavor": "legacy_unscoped",
        "connection_mode": "keepalive",
        "payload_bytes": math.nan,
        "spec_fingerprint": "",
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default
        else:
            df[col] = df[col].fillna(default)

    df["baseline_for_flavor"] = df["baseline_for_flavor"].replace("", "legacy_unscoped").fillna("legacy_unscoped")

    metrics = df.apply(primary_metric, axis=1, result_type="expand")
    metrics.columns = ["primary_metric", "primary_unit", "primary_value"]
    df = pd.concat([df, metrics], axis=1)
    df["p99_effective_ms"] = df.apply(p99_value, axis=1)
    df["failure_percent_effective"] = df.apply(failure_percent, axis=1)

    octavia = df[df["target_kind"] == "octavia"].copy()
    direct = df[df["target_kind"] == "direct"].copy()

    if args.flavor:
        octavia = octavia[octavia["octavia_flavor"].astype(str).isin(args.flavor)]
        direct = direct[
            direct["baseline_for_flavor"].astype(str).isin(args.flavor)
            | (direct["baseline_for_flavor"].astype(str) == "legacy_unscoped")
        ]
    if args.scenario:
        octavia = octavia[octavia["scenario_name"].astype(str).isin(args.scenario)]
        direct = direct[direct["scenario_name"].astype(str).isin(args.scenario)]

    if octavia.empty:
        available = sorted({str(x) for x in df.loc[df["target_kind"] == "octavia", "octavia_flavor"].dropna()})
        raise SystemExit(
            "No matching Octavia results found. Available flavors: " + (", ".join(available) if available else "none")
        )

    selected = choose_latest(
        octavia,
        ["scenario_name", "traffic_path", "generator_network_mode", "octavia_flavor"],
        args.latest_per_group,
    )
    summary = aggregate_octavia(selected)

    # Fingerprint compatibility must be evaluated across all flavors in the
    # same scenario/path/topology population, not only within one flavor.
    population_fp = (
        selected.groupby(["scenario_name", "traffic_path", "generator_network_mode"], dropna=False)["spec_fingerprint"]
        .agg(
            population_fingerprint_count=lambda s: len({str(x) for x in s.dropna() if str(x)}),
            population_fingerprints=lambda s: ",".join(sorted({str(x) for x in s.dropna() if str(x)})),
        )
        .reset_index()
    )
    summary = summary.merge(
        population_fp,
        on=["scenario_name", "traffic_path", "generator_network_mode"],
        how="left",
    )
    summary = add_relative_metrics(summary, args.reference_flavor)
    direct_summary = aggregate_direct(direct, args.latest_direct)
    if not direct_summary.empty:
        scoped_direct = direct_summary[direct_summary["baseline_for_flavor"] != "legacy_unscoped"].copy()
        if not scoped_direct.empty:
            summary = summary.merge(
                scoped_direct,
                left_on=["scenario_name", "generator_network_mode", "octavia_flavor"],
                right_on=["scenario_name", "generator_network_mode", "baseline_for_flavor"],
                how="left",
            )
            summary["percent_of_direct"] = summary["median_primary"] / summary["direct_median_primary"] * 100.0
        else:
            summary["percent_of_direct"] = math.nan
    else:
        summary["percent_of_direct"] = math.nan

    scorecard = flavor_scorecard(summary)
    winners = scenario_winners(summary)
    make_charts(out, summary, scorecard)
    write_reports(out, selected, summary, direct_summary, scorecard, winners, args.reference_flavor, args.latest_per_group)

    warning_groups = int(
        summary.loc[summary["population_fingerprint_count"] > 1, ["scenario_name", "traffic_path", "generator_network_mode"]]
        .drop_duplicates()
        .shape[0]
    )
    print(f"Scanned results: {root}")
    print(f"Selected Octavia runs: {len(selected)}")
    print(f"Flavors: {', '.join(str(x) for x in scorecard['octavia_flavor'].tolist())}")
    print(f"Scenario populations: {summary[['scenario_name','traffic_path','generator_network_mode']].drop_duplicates().shape[0]}")
    print(f"Fingerprint-warning groups: {warning_groups}")
    print(f"Report: {out / 'README.md'}")
    print(f"Detailed: {out / 'DETAILED_COMPARISON.md'}")
    print(f"Dashboard: {out / 'charts' / 'composite-dashboard.png'}")
    print(f"CSV: {out / 'scenario-summary.csv'}")
    if args.strict_fingerprint and warning_groups:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

