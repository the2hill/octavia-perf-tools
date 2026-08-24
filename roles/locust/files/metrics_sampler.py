#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import socket
import time
from pathlib import Path


def cpu_times() -> tuple[int, int]:
    fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    values = [int(v) for v in fields]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def mem() -> tuple[int, int]:
    vals = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1)
        vals[k] = int(v.strip().split()[0])
    return vals.get("MemTotal", 0), vals.get("MemAvailable", 0)


def net() -> tuple[int, int, int, int]:
    rx_b = tx_b = rx_p = tx_p = 0
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        name, data = line.split(":", 1)
        if name.strip() == "lo":
            continue
        f = data.split()
        rx_b += int(f[0]); rx_p += int(f[1]); tx_b += int(f[8]); tx_p += int(f[9])
    return rx_b, tx_b, rx_p, tx_p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    host = socket.gethostname()
    prev_total, prev_idle = cpu_times()
    prev_rx_b, prev_tx_b, prev_rx_p, prev_tx_p = net()
    prev_t = time.monotonic()

    with out.open("w", newline="", buffering=1) as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp_epoch","host","cpu_percent","mem_used_percent","load1",
                    "rx_bytes_per_sec","tx_bytes_per_sec","rx_packets_per_sec","tx_packets_per_sec"])
        while True:
            time.sleep(args.interval)
            now = time.monotonic()
            elapsed = max(now - prev_t, 0.001)
            total, idle = cpu_times()
            dtotal, didle = total - prev_total, idle - prev_idle
            cpu = 0.0 if dtotal <= 0 else 100.0 * (1.0 - didle / dtotal)
            mt, ma = mem()
            mem_used = 0.0 if mt <= 0 else 100.0 * (1.0 - ma / mt)
            rx_b, tx_b, rx_p, tx_p = net()
            load1 = os.getloadavg()[0]
            w.writerow([
                f"{time.time():.3f}", host, f"{cpu:.3f}", f"{mem_used:.3f}", f"{load1:.3f}",
                f"{(rx_b-prev_rx_b)/elapsed:.3f}", f"{(tx_b-prev_tx_b)/elapsed:.3f}",
                f"{(rx_p-prev_rx_p)/elapsed:.3f}", f"{(tx_p-prev_tx_p)/elapsed:.3f}",
            ])
            prev_total, prev_idle = total, idle
            prev_rx_b, prev_tx_b, prev_rx_p, prev_tx_p = rx_b, tx_b, rx_p, tx_p
            prev_t = now


if __name__ == "__main__":
    main()
