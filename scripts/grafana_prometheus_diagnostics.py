#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import ssl
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

import yaml


SCHEMA_VERSION = 1


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text())
    return value if isinstance(value, dict) else {}


def parse_utc(value: Any) -> dt.datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("missing UTC timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def percentile(values: list[float], fraction: float) -> float | None:
    clean = sorted(v for v in values if math.isfinite(v))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pos = (len(clean) - 1) * fraction
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return clean[lower]
    weight = pos - lower
    return clean[lower] * (1.0 - weight) + clean[upper] * weight


def stats(values: list[float]) -> dict[str, float | int | None]:
    clean = [v for v in values if math.isfinite(v)]
    if not clean:
        return {"samples": 0, "avg": None, "max": None, "p95": None, "last": None}
    return {
        "samples": len(clean),
        "avg": sum(clean) / len(clean),
        "max": max(clean),
        "p95": percentile(clean, 0.95),
        "last": clean[-1],
    }


def safe_error_body(exc: urlerror.HTTPError) -> str:
    try:
        body = exc.read(4096).decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
    return body


def ssl_context(verify_tls: bool, ca_file: str | None) -> ssl.SSLContext | None:
    if verify_tls:
        return ssl.create_default_context(cafile=ca_file or None)
    return ssl._create_unverified_context()  # noqa: SLF001 - explicit operator option


def query_range(
    *,
    grafana_url: str,
    datasource_uid: str,
    token: str,
    promql: str,
    start: dt.datetime,
    end: dt.datetime,
    step_seconds: int,
    timeout_seconds: float,
    verify_tls: bool,
    ca_file: str | None,
) -> list[dict[str, Any]]:
    proxy = (
        grafana_url.rstrip("/")
        + "/api/datasources/proxy/uid/"
        + urlparse.quote(datasource_uid, safe="")
        + "/api/v1/query_range"
    )
    params = urlparse.urlencode(
        {
            "query": promql,
            "start": f"{start.timestamp():.3f}",
            "end": f"{end.timestamp():.3f}",
            "step": str(step_seconds),
        }
    )
    req = urlrequest.Request(
        f"{proxy}?{params}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "octavia-perf-tool/grafana-prometheus-diagnostics",
        },
        method="GET",
    )
    try:
        with urlrequest.urlopen(
            req,
            timeout=timeout_seconds,
            context=ssl_context(verify_tls, ca_file),
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        body = safe_error_body(exc)
        detail = f": {body}" if body else ""
        raise RuntimeError(f"Grafana datasource proxy returned HTTP {exc.code}{detail}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"unable to reach Grafana: {exc.reason}") from exc

    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed through Grafana: {payload}")
    data = payload.get("data") or {}
    if data.get("resultType") != "matrix":
        raise RuntimeError(f"expected Prometheus matrix result, got {data.get('resultType')!r}")
    result = data.get("result") or []
    return result if isinstance(result, list) else []


def summarize_matrix(result: list[dict[str, Any]]) -> dict[str, Any]:
    series: list[dict[str, Any]] = []
    all_values: list[float] = []
    for item in result:
        labels = item.get("metric") or {}
        samples: list[list[float]] = []
        values: list[float] = []
        for pair in item.get("values") or []:
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            try:
                ts = float(pair[0])
                value = float(pair[1])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            samples.append([ts, value])
            values.append(value)
            all_values.append(value)
        series.append(
            {
                "labels": labels,
                "stats": stats(values),
                "samples": samples,
            }
        )
    return {
        "series_count": len(series),
        "stats_across_all_series_samples": stats(all_values),
        "series": series,
    }


def metric_summary(metrics: dict[str, Any], name: str) -> dict[str, Any]:
    item = metrics.get(name) or {}
    return (item.get("result") or {}).get("stats_across_all_series_samples") or {}


def max_series_stat(metrics: dict[str, Any], name: str, stat_name: str = "max") -> float | None:
    item = metrics.get(name) or {}
    series = ((item.get("result") or {}).get("series") or [])
    values: list[float] = []
    for row in series:
        value = (row.get("stats") or {}).get(stat_name)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            values.append(float(value))
    return max(values) if values else None


def promql_string(value: str) -> str:
    """Escape a value for use inside a double-quoted PromQL string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_queries(domain_regex: str, rate_window_seconds: int) -> dict[str, str]:
    selector = f'domain=~"{promql_string(domain_regex)}"'
    window = f"{rate_window_seconds}s"
    cpu = f'rate(libvirt_domain_vcpu_time_seconds_total{{{selector}}}[{window}])'
    delay = f'rate(libvirt_domain_vcpu_delay_seconds_total{{{selector}}}[{window}])'
    wait = f'rate(libvirt_domain_vcpu_wait_seconds_total{{{selector}}}[{window}])'
    rx_bytes = f'rate(libvirt_domain_interface_stats_receive_bytes_total{{{selector}}}[{window}])'
    tx_bytes = f'rate(libvirt_domain_interface_stats_transmit_bytes_total{{{selector}}}[{window}])'
    rx_packets = f'rate(libvirt_domain_interface_stats_receive_packets_total{{{selector}}}[{window}])'
    tx_packets = f'rate(libvirt_domain_interface_stats_transmit_packets_total{{{selector}}}[{window}])'
    rx_errors = f'rate(libvirt_domain_interface_stats_receive_errors_total{{{selector}}}[{window}])'
    tx_errors = f'rate(libvirt_domain_interface_stats_transmit_errors_total{{{selector}}}[{window}])'
    vcpus = f'max by (domain) (libvirt_domain_info_virtual_cpus{{{selector}}})'
    return {
        "cpu_cores_total": f"sum({cpu})",
        "cpu_percent_normalized": f"100 * sum({cpu}) / sum({vcpus})",
        "per_vcpu_cpu_percent": f"100 * {cpu}",
        "allocated_vcpus": f"sum({vcpus})",
        "per_vcpu_delay_seconds_per_second": delay,
        "per_vcpu_wait_seconds_per_second": wait,
        "rx_bytes_per_second": f"sum({rx_bytes})",
        "tx_bytes_per_second": f"sum({tx_bytes})",
        "rx_packets_per_second": f"sum({rx_packets})",
        "tx_packets_per_second": f"sum({tx_packets})",
        "rx_errors_per_second": f"sum({rx_errors})",
        "tx_errors_per_second": f"sum({tx_errors})",
    }


def collect(config_path: Path, result_dir: Path) -> dict[str, Any]:
    cfg = load_yaml(config_path)
    grafana_cfg = cfg.get("grafana") or {}
    enabled = bool(grafana_cfg.get("enabled", False))
    output: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "collector": "grafana_prometheus_proxy",
        "status": "disabled" if not enabled else "starting",
        "collected_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    }
    if not enabled:
        return output

    target = load_yaml(result_dir / "target.yml")
    timing = load_yaml(result_dir / "timing.yml")
    if str(target.get("target_kind") or "") != "octavia":
        output.update({"status": "skipped", "reason": "target_kind is not octavia"})
        return output

    domains = [str(x) for x in (target.get("prometheus_libvirt_domains") or []) if str(x)]
    if not domains and target.get("amphora_instance_name"):
        domains = [str(target["amphora_instance_name"])]
    if not domains:
        output.update({"status": "skipped", "reason": "no Amphora libvirt domain identity in target.yml"})
        return output

    grafana_url = str(grafana_cfg.get("url") or "").strip()
    datasource_uid = str(grafana_cfg.get("prometheus_datasource_uid") or "").strip()
    token_env = str(grafana_cfg.get("token_env") or "GRAFANA_TOKEN").strip()
    token = os.environ.get(token_env, "").strip()
    if not grafana_url:
        raise ValueError("grafana.url is required when grafana.enabled=true")
    if not datasource_uid:
        raise ValueError("grafana.prometheus_datasource_uid is required when grafana.enabled=true")
    if not token:
        raise ValueError(f"Grafana token environment variable {token_env!r} is empty or unset")

    start = parse_utc(timing.get("load_test_started_at_utc"))
    end = parse_utc(timing.get("load_test_completed_at_utc"))
    if end <= start:
        raise ValueError("load_test_completed_at_utc must be after load_test_started_at_utc")

    step_seconds = int(grafana_cfg.get("step_seconds", 15))
    rate_window_seconds = int(grafana_cfg.get("rate_window_seconds", 60))
    timeout_seconds = float(grafana_cfg.get("timeout_seconds", 30))
    verify_tls = bool(grafana_cfg.get("verify_tls", True))
    ca_file_raw = grafana_cfg.get("ca_file")
    ca_file = str(ca_file_raw) if ca_file_raw else None
    domain_regex = "(?:" + "|".join(re.escape(x) for x in domains) + ")"

    output.update(
        {
            "status": "collecting",
            "grafana_url": grafana_url,
            "prometheus_datasource_uid": datasource_uid,
            "token_env": token_env,
            "query_window": {
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat(),
                "elapsed_seconds": (end - start).total_seconds(),
                "step_seconds": step_seconds,
                "rate_window_seconds": rate_window_seconds,
            },
            "domains": domains,
            "domain_regex": domain_regex,
            "metrics": {},
        }
    )

    queries = build_queries(domain_regex, rate_window_seconds)
    metrics: dict[str, Any] = {}
    query_errors: dict[str, str] = {}
    for name, promql in queries.items():
        try:
            matrix = query_range(
                grafana_url=grafana_url,
                datasource_uid=datasource_uid,
                token=token,
                promql=promql,
                start=start,
                end=end,
                step_seconds=step_seconds,
                timeout_seconds=timeout_seconds,
                verify_tls=verify_tls,
                ca_file=ca_file,
            )
            metrics[name] = {"promql": promql, "result": summarize_matrix(matrix)}
        except Exception as exc:
            query_errors[name] = f"{type(exc).__name__}: {exc}"
            metrics[name] = {"promql": promql, "error": query_errors[name]}

    output["metrics"] = metrics
    if query_errors:
        output["query_errors"] = query_errors

    summary = {
        "avg_cpu_cores": metric_summary(metrics, "cpu_cores_total").get("avg"),
        "peak_cpu_cores": metric_summary(metrics, "cpu_cores_total").get("max"),
        "avg_cpu_percent": metric_summary(metrics, "cpu_percent_normalized").get("avg"),
        "peak_cpu_percent": metric_summary(metrics, "cpu_percent_normalized").get("max"),
        "allocated_vcpus": metric_summary(metrics, "allocated_vcpus").get("max"),
        "hottest_vcpu_percent": max_series_stat(metrics, "per_vcpu_cpu_percent"),
        "peak_vcpu_delay_seconds_per_second": max_series_stat(metrics, "per_vcpu_delay_seconds_per_second"),
        "peak_vcpu_wait_seconds_per_second": max_series_stat(metrics, "per_vcpu_wait_seconds_per_second"),
        "peak_rx_bytes_per_second": metric_summary(metrics, "rx_bytes_per_second").get("max"),
        "peak_tx_bytes_per_second": metric_summary(metrics, "tx_bytes_per_second").get("max"),
        "peak_rx_packets_per_second": metric_summary(metrics, "rx_packets_per_second").get("max"),
        "peak_tx_packets_per_second": metric_summary(metrics, "tx_packets_per_second").get("max"),
        "peak_rx_errors_per_second": metric_summary(metrics, "rx_errors_per_second").get("max"),
        "peak_tx_errors_per_second": metric_summary(metrics, "tx_errors_per_second").get("max"),
    }
    output["summary"] = summary

    successful_queries = sum(1 for item in metrics.values() if "result" in item)
    output["successful_queries"] = successful_queries
    output["failed_queries"] = len(query_errors)
    output["status"] = "ok" if successful_queries and not query_errors else ("partial" if successful_queries else "error")
    return output


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Collect historical Amphora libvirt metrics through Grafana's Prometheus datasource proxy"
    )
    ap.add_argument("--config", required=True)
    ap.add_argument("--result-dir", required=True)
    ap.add_argument("--output")
    ap.add_argument("--strict", action="store_true", help="exit non-zero when collection fails")
    args = ap.parse_args()

    config_path = Path(args.config)
    result_dir = Path(args.result_dir)
    output_path = Path(args.output) if args.output else result_dir / "prometheus-diagnostics.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        payload = collect(config_path, result_dir)
    except Exception as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "collector": "grafana_prometheus_proxy",
            "status": "error",
            "collected_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
        print(f"WARNING: Grafana/Prometheus diagnostics collection failed: {exc}")
        print(f"Diagnostics status: {output_path}")
        if args.strict:
            raise SystemExit(1) from exc
        return

    output_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    print(f"Grafana/Prometheus diagnostics: status={payload.get('status')} output={output_path}")
    if args.strict and payload.get("status") not in {"ok", "disabled", "skipped"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
