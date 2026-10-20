#!/usr/bin/env python3
"""Record compact per-generator capacity telemetry every N seconds."""
import argparse
import csv
import datetime as dt
import glob
import ipaddress
import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path

FIELDS = [
    "epoch", "utc", "host", "vip", "port", "vip_established", "tcp_established",
    "worker_count", "worker_rss_mb", "worker_pss_mb", "worker_fds",
    "mem_available_mb", "swap_free_mb", "psi_some_avg10", "psi_full_avg10",
    "stage_target", "stage_workers_seen",
]
STOP = False


def stop(_sig, _frame):
    global STOP
    STOP = True


def command(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def endpoint_matches(peer, vip, port):
    peer = peer.strip()
    if peer.startswith("["):
        idx = peer.rfind("]:")
        if idx < 0:
            return False
        host, port_text = peer[1:idx], peer[idx + 2:]
    else:
        host, sep, port_text = peer.rpartition(":")
        if not sep:
            return False
    try:
        return int(port_text) == port and ipaddress.ip_address(host) == ipaddress.ip_address(vip)
    except ValueError:
        return False


def socket_counts(vip, port):
    lines = command(["ss", "-Htn", "state", "established"]).splitlines()
    total = matched = 0
    for line in lines:
        parts = line.split()
        # With ss -H, the header (including "State") is omitted, leaving
        # four columns: Recv-Q Send-Q Local-Address:Port Peer-Address:Port.
        if len(parts) < 4:
            continue
        total += 1
        if endpoint_matches(parts[3], vip, port):
            matched += 1
    return matched, total


def worker_pids():
    result = []
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            argv = [arg.decode(errors="ignore") for arg in (proc_dir / "cmdline").read_bytes().split(b"\0") if arg]
            if any(os.path.basename(arg) == "connection_capacity.py" for arg in argv):
                result.append(int(proc_dir.name))
        except OSError:
            continue
    return result


def proc_stats(pid):
    try:
        status = Path(f"/proc/{pid}/status").read_text()
        match = re.search(r"^VmRSS:\s+(\d+)", status, re.M)
        rss_mb = float(match.group(1)) / 1024 if match else 0.0
    except OSError:
        return 0.0, 0.0, 0
    try:
        rollup = Path(f"/proc/{pid}/smaps_rollup").read_text()
        match = re.search(r"^Pss:\s+(\d+)", rollup, re.M)
        pss_mb = float(match.group(1)) / 1024 if match else 0.0
    except OSError:
        pss_mb = 0.0
    try:
        fds = len(list(Path(f"/proc/{pid}/fd").iterdir()))
    except OSError:
        fds = 0
    return rss_mb, pss_mb, fds


def memory():
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, value = line.partition(":")
            if key in ("MemAvailable", "SwapFree"):
                values[key] = float(value.split()[0]) / 1024
    except OSError:
        pass
    return values.get("MemAvailable", 0.0), values.get("SwapFree", 0.0)


def psi(kind):
    try:
        for line in Path("/proc/pressure/memory").read_text().splitlines():
            if line.startswith(kind + " "):
                match = re.search(r"\bavg10=([0-9.]+)", line)
                return float(match.group(1)) if match else 0.0
    except OSError:
        pass
    return 0.0


def stage(log_dir):
    """Best-effort stage inference from active worker logs; zero means unknown."""
    if not log_dir:
        return 0, 0
    found = {}
    for path in glob.glob(os.path.join(log_dir, "connection-capacity-p*.log")):
        try:
            content = Path(path).read_text(errors="replace")
            matches = re.findall(r"\b(?:level|target_global)=(\d+)", content)
            if matches:
                found[path] = (os.path.getmtime(path), int(matches[-1]))
        except OSError:
            pass
    if not found:
        return 0, 0
    latest = max(found, key=lambda path: found[path][0])
    target = found[latest][1]
    return target, sum(1 for _, value in found.values() if value == target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vip", help="Target VIP address passed by run_test.yml; no summary.json required")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--out", default="/var/tmp/capacity-watch.csv")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--log-dir", help="Remote run directory containing connection-capacity-p*.log")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be >= 1 second")
    try:
        ipaddress.ip_address(args.vip)
    except ValueError:
        parser.error(f"VIP must be an IP address, got {args.vip!r}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    new_file = not Path(args.out).exists() or Path(args.out).stat().st_size == 0
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with open(args.out, "a", newline="", buffering=1) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        while not STOP:
            now = time.time()
            vip_count, tcp_count = socket_counts(args.vip, args.port)
            pids = worker_pids()
            rss = pss = fds = 0.0
            for pid in pids:
                r, p, f = proc_stats(pid)
                rss += r
                pss += p
                fds += f
            available, swap = memory()
            target, workers_seen = stage(args.log_dir)
            writer.writerow({
                "epoch": f"{now:.3f}",
                "utc": dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "host": socket.gethostname().split(".")[0],
                "vip": args.vip, "port": args.port,
                "vip_established": vip_count, "tcp_established": tcp_count,
                "worker_count": len(pids), "worker_rss_mb": f"{rss:.1f}",
                "worker_pss_mb": f"{pss:.1f}", "worker_fds": int(fds),
                "mem_available_mb": f"{available:.1f}", "swap_free_mb": f"{swap:.1f}",
                "psi_some_avg10": f"{psi('some'):.2f}", "psi_full_avg10": f"{psi('full'):.2f}",
                "stage_target": target, "stage_workers_seen": workers_seen,
            })
            deadline = now + args.interval
            while not STOP and time.time() < deadline:
                time.sleep(min(0.25, max(0.01, deadline - time.time())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
