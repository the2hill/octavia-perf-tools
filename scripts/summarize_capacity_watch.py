#!/usr/bin/env python3
"""Summarize fetched capacity-watch CSVs into one copy/pasteable report."""
import argparse
import csv
import glob
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone

COLS = ["vip_established", "tcp_established", "worker_count", "worker_rss_mb", "worker_pss_mb", "worker_fds", "mem_available_mb", "swap_free_mb", "psi_some_avg10", "psi_full_avg10", "stage_target", "stage_workers_seen"]


def num(row, key):
    try:
        return float(row.get(key) or 0)
    except (ValueError, TypeError):
        return 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Directory containing fetched capacity-watch*.csv")
    parser.add_argument("--bucket", type=int, default=30)
    parser.add_argument("--expected-hosts", type=int, default=16)
    parser.add_argument("--vip", default="read from watcher CSV")
    parser.add_argument("--output", default="capacity-watch-summary.txt")
    args = parser.parse_args()
    width = max(1, args.bucket)
    rows = []
    for path in glob.glob(os.path.join(args.directory, "**", "capacity-watch*.csv"), recursive=True):
        try:
            with open(path, newline="") as stream:
                rows.extend(row for row in csv.DictReader(stream) if row.get("host") and row.get("epoch"))
        except (OSError, csv.Error):
            pass
    if not rows:
        raise SystemExit(f"No capacity-watch*.csv files under {args.directory}")

    hosts = defaultdict(list)
    bucket_hosts = defaultdict(list)
    for row in rows:
        hosts[row["host"]].append(row)
        bucket = int(float(row["epoch"]) // width) * width
        bucket_hosts[(bucket, row["host"])].append(row)

    detected_vips = sorted({f"{row.get('vip','?')}:{row.get('port','?')}" for row in rows})
    vip_label = args.vip if args.vip != "read from watcher CSV" else ",".join(detected_vips)
    lines = [
        "OCTAVIA CONNECTION-CAPACITY TELEMETRY",
        f"VIP: {vip_label} | Hosts: {len(hosts)}/{args.expected_hosts} | Samples: {len(rows)} | Bucket: {width}s",
        "",
        "PER-HOST PEAKS / LOWS",
        "host,vip_peak,tcp_peak,workers_peak,rss_peak_mb,pss_peak_mb,fds_peak,mem_available_min_mb,psi_some_peak,psi_full_peak",
    ]
    for host, samples in sorted(hosts.items()):
        values = {key: [num(row, key) for row in samples] for key in COLS}
        lines.append(",".join([
            host, str(round(max(values["vip_established"]))), str(round(max(values["tcp_established"]))),
            str(round(max(values["worker_count"]))), f"{max(values['worker_rss_mb']):.0f}",
            f"{max(values['worker_pss_mb']):.0f}", str(round(max(values["worker_fds"]))),
            f"{min(values['mem_available_mb']):.0f}", f"{max(values['psi_some_avg10']):.2f}",
            f"{max(values['psi_full_avg10']):.2f}",
        ]))

    timeline = defaultdict(list)
    for (bucket, host), samples in bucket_hosts.items():
        record = {"host": host}
        for key in COLS:
            record[key] = statistics.median(num(row, key) for row in samples)
        timeline[bucket].append(record)
    lines += [
        "", f"TIMELINE ({width}s buckets; counts/resources summed across reporting hosts)",
        "utc,hosts_seen,stage_target,vip_sum,tcp_sum,workers_sum,rss_sum_mb,pss_sum_mb,fds_sum,mem_available_min_mb,psi_some_max,psi_full_max",
    ]
    for bucket, records in sorted(timeline.items()):
        targets = [int(record["stage_target"]) for record in records if record["stage_target"] > 0]
        target = max(set(targets), key=targets.count) if targets else 0
        total = lambda key: sum(record[key] for record in records)
        lines.append(",".join([
            datetime.fromtimestamp(bucket, timezone.utc).strftime("%H:%M:%S"), str(len(records)), str(target),
            str(round(total("vip_established"))), str(round(total("tcp_established"))),
            str(round(total("worker_count"))), str(round(total("worker_rss_mb"))),
            str(round(total("worker_pss_mb"))), str(round(total("worker_fds"))),
            f"{min(record['mem_available_mb'] for record in records):.0f}",
            f"{max(record['psi_some_avg10'] for record in records):.2f}",
            f"{max(record['psi_full_avg10'] for record in records):.2f}",
        ]))

    lines += ["", "WARNINGS"]
    if len(hosts) < args.expected_hosts:
        lines.append(f"- Only {len(hosts)}/{args.expected_hosts} expected hosts reported.")
    if all(num(row, "vip_established") == 0 for row in rows):
        lines.append("- VIP count was zero in every sample. Check target host/port and compare with TCP total.")
    if all(num(row, "stage_target") == 0 for row in rows):
        lines.append("- Stage target was not available in worker logs; the time series is still useful, but target correlation is incomplete.")
    max_psi = max(num(row, "psi_full_avg10") for row in rows)
    lines.append(f"- Peak memory full-pressure avg10: {max_psi:.2f}%" + (" (investigate pressure)." if max_psi >= 1 else " (no sample reached 1%)."))
    lines += ["", "Notes: RSS may double-count shared pages; PSS is a better aggregate. hosts_seen shows sample coverage.", "Copy/paste this report only; raw per-host samples remain in CSV files."]
    report = "\n".join(lines) + "\n"
    with open(args.output, "w", encoding="utf-8") as stream:
        stream.write(report)
    print(f"Wrote {args.output}\n\n{report}")


if __name__ == "__main__":
    main()
