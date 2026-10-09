#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import math
import os
import socket
import ssl
import struct
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass
class HeldConnection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter


class CapacityRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        parsed = urlsplit(args.target_url)
        if parsed.scheme not in {"http", "https"}:
            raise SystemExit("target URL must use http or https")
        self.scheme = parsed.scheme
        self.host = parsed.hostname
        if not self.host:
            raise SystemExit("target URL is missing a host")
        self.port = parsed.port or (443 if self.scheme == "https" else 80)
        self.host_header = parsed.hostname if parsed.port is None else f"{parsed.hostname}:{parsed.port}"
        self.ssl_context = self._build_ssl_context() if self.scheme == "https" else None
        self.open_sem = asyncio.Semaphore(args.open_concurrency)
        self.io_sem = asyncio.Semaphore(args.io_concurrency)
        self.output_dir = Path(args.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        suffix = f"-{args.output_prefix}" if args.output_prefix else ""
        self.summary_path = self.output_dir / f"connection-capacity{suffix}.csv"
        self.latency_path = self.output_dir / f"connection-latencies{suffix}.csv"
        self.errors_path = self.output_dir / f"connection-errors{suffix}.csv"

    def _build_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        if self.args.insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    @staticmethod
    def worker_share(global_target: int, worker_index: int, worker_count: int) -> int:
        base, remainder = divmod(global_target, worker_count)
        return base + (1 if worker_index < remainder else 0)

    async def open_one(self) -> tuple[HeldConnection | None, float, str | None]:
        started = time.perf_counter()
        try:
            async with self.open_sem:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self.host,
                        self.port,
                        ssl=self.ssl_context,
                        server_hostname=(self.host if self.ssl_context else None),
                    ),
                    timeout=self.args.connect_timeout,
                )
                raw_sock = writer.get_extra_info("socket")
                if raw_sock is not None and self.args.tcp_nodelay:
                    raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn = HeldConnection(reader=reader, writer=writer)
                if self.args.capacity_mode == "active":
                    await self.http_exchange(conn)
                latency_ms = (time.perf_counter() - started) * 1000.0
                return conn, latency_ms, None
        except Exception as exc:  # noqa: BLE001 - benchmark must classify all failures
            latency_ms = (time.perf_counter() - started) * 1000.0
            return None, latency_ms, self.error_key(exc)

    async def http_exchange(self, conn: HeldConnection) -> None:
        async with self.io_sem:
            request = (
                f"GET {self.args.path} HTTP/1.1\r\n"
                f"Host: {self.host_header}\r\n"
                "User-Agent: octavia-perf-connection-capacity/1\r\n"
                "Accept: */*\r\n"
                "Connection: keep-alive\r\n\r\n"
            ).encode("ascii")
            conn.writer.write(request)
            await asyncio.wait_for(conn.writer.drain(), timeout=self.args.request_timeout)
            header_blob = await asyncio.wait_for(
                conn.reader.readuntil(b"\r\n\r\n"), timeout=self.args.request_timeout
            )
            lines = header_blob.decode("iso-8859-1", errors="replace").split("\r\n")
            if not lines or " " not in lines[0]:
                raise RuntimeError("invalid_http_status")
            try:
                status = int(lines[0].split(" ", 2)[1])
            except (IndexError, ValueError) as exc:
                raise RuntimeError("invalid_http_status") from exc
            if status != 200:
                raise RuntimeError(f"http_{status}")
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip().lower()
            if "content-length" in headers:
                length = int(headers["content-length"])
                if length:
                    await asyncio.wait_for(conn.reader.readexactly(length), timeout=self.args.request_timeout)
            elif headers.get("transfer-encoding") == "chunked":
                await self.read_chunked(conn.reader)
            else:
                raise RuntimeError("response_without_length")

    async def read_chunked(self, reader: asyncio.StreamReader) -> None:
        while True:
            size_line = await asyncio.wait_for(reader.readline(), timeout=self.args.request_timeout)
            size = int(size_line.split(b";", 1)[0].strip(), 16)
            if size == 0:
                await asyncio.wait_for(reader.readuntil(b"\r\n"), timeout=self.args.request_timeout)
                return
            await asyncio.wait_for(reader.readexactly(size + 2), timeout=self.args.request_timeout)

    @staticmethod
    def error_key(exc: Exception) -> str:
        if isinstance(exc, asyncio.TimeoutError):
            return "timeout"
        if isinstance(exc, ssl.SSLError):
            return f"ssl:{exc.__class__.__name__}"
        if isinstance(exc, OSError):
            errno_value = getattr(exc, "errno", None)
            return f"oserror:{errno_value if errno_value is not None else exc.__class__.__name__}"
        text = str(exc).strip().replace(",", ";")[:100]
        return f"{exc.__class__.__name__}:{text}" if text else exc.__class__.__name__

    async def open_level(self, target: int) -> tuple[list[HeldConnection], list[float], Counter[str], float]:
        if target <= 0:
            return [], [], Counter(), 0.0
        started = time.perf_counter()
        connections: list[HeldConnection] = []
        latencies: list[float] = []
        errors: Counter[str] = Counter()
        ramp = max(0.001, float(self.args.ramp_seconds))
        pacing_slices = max(1, int(ramp * 10))
        batch_size = max(1, min(self.args.open_concurrency, math.ceil(target / pacing_slices)))
        attempted = 0

        while attempted < target:
            batch_n = min(batch_size, target - attempted)
            desired_elapsed = (attempted / target) * ramp
            now_elapsed = time.perf_counter() - started
            if desired_elapsed > now_elapsed:
                await asyncio.sleep(desired_elapsed - now_elapsed)
            results = await asyncio.gather(*(self.open_one() for _ in range(batch_n)))
            attempted += batch_n
            for conn, latency_ms, error in results:
                if conn is not None:
                    connections.append(conn)
                    latencies.append(latency_ms)
                else:
                    errors[error or "unknown"] += 1

        return connections, latencies, errors, time.perf_counter() - started

    async def verify_connections(self, connections: list[HeldConnection]) -> tuple[list[HeldConnection], Counter[str]]:
        async def check(conn: HeldConnection) -> tuple[HeldConnection | None, str | None]:
            try:
                await self.http_exchange(conn)
                return conn, None
            except Exception as exc:  # noqa: BLE001
                return None, self.error_key(exc)

        survivors: list[HeldConnection] = []
        errors: Counter[str] = Counter()
        chunk = max(1, self.args.io_concurrency * 2)
        for offset in range(0, len(connections), chunk):
            results = await asyncio.gather(*(check(c) for c in connections[offset : offset + chunk]))
            for conn, error in results:
                if conn is not None:
                    survivors.append(conn)
                else:
                    errors[error or "unknown"] += 1
        return survivors, errors

    async def hold_level(self, connections: list[HeldConnection]) -> tuple[list[HeldConnection], Counter[str]]:
        errors: Counter[str] = Counter()
        if not connections:
            return connections, errors
        if self.args.capacity_mode == "idle":
            await asyncio.sleep(self.args.hold_seconds)
            if self.args.verify_idle_at_end:
                return await self.verify_connections(connections)
            return connections, errors

        deadline = time.monotonic() + self.args.hold_seconds
        survivors = connections
        while survivors and time.monotonic() < deadline:
            sleep_for = min(self.args.heartbeat_seconds, max(0.0, deadline - time.monotonic()))
            if sleep_for:
                await asyncio.sleep(sleep_for)
            if time.monotonic() >= deadline and self.args.skip_final_heartbeat:
                break
            survivors, heartbeat_errors = await self.verify_connections(survivors)
            errors.update(heartbeat_errors)
        return survivors, errors

    def close_all(self, connections: list[HeldConnection]) -> None:
        linger = struct.pack("ii", 1, 0)
        for conn in connections:
            try:
                raw_sock = conn.writer.get_extra_info("socket")
                if self.args.abortive_close and raw_sock is not None:
                    raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
            except OSError:
                pass
            try:
                conn.writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def run(self) -> None:
        levels = self.args.levels
        start_wait = self.args.start_epoch - time.time()
        if start_wait > 0:
            await asyncio.sleep(start_wait)

        with self.summary_path.open("w", newline="") as summary_file, self.latency_path.open(
            "w", newline=""
        ) as latency_file, self.errors_path.open("w", newline="") as errors_file:
            summary_writer = csv.DictWriter(
                summary_file,
                fieldnames=[
                    "worker_index",
                    "worker_count",
                    "capacity_mode",
                    "target_global",
                    "target_worker",
                    "attempted",
                    "established",
                    "establish_failed",
                    "surviving",
                    "survival_failed",
                    "ramp_elapsed_seconds",
                    "established_per_second",
                    "level_elapsed_seconds",
                ],
            )
            latency_writer = csv.DictWriter(
                latency_file, fieldnames=["worker_index", "target_global", "latency_ms"]
            )
            errors_writer = csv.DictWriter(
                errors_file, fieldnames=["worker_index", "target_global", "phase", "error", "count"]
            )
            summary_writer.writeheader()
            latency_writer.writeheader()
            errors_writer.writeheader()

            for level_index, global_target in enumerate(levels):
                level_started = time.perf_counter()
                worker_target = self.worker_share(global_target, self.args.worker_index, self.args.worker_count)
                print(
                    f"worker={self.args.worker_index}/{self.args.worker_count} "
                    f"level={global_target} worker_target={worker_target} mode={self.args.capacity_mode}",
                    flush=True,
                )
                connections, latencies, establish_errors, ramp_elapsed = await self.open_level(worker_target)
                established = len(connections)
                survivors, survival_errors = await self.hold_level(connections)
                surviving = len(survivors)

                for latency in latencies:
                    latency_writer.writerow(
                        {
                            "worker_index": self.args.worker_index,
                            "target_global": global_target,
                            "latency_ms": f"{latency:.6f}",
                        }
                    )
                for phase, counter in (("establish", establish_errors), ("survival", survival_errors)):
                    for error, count in sorted(counter.items()):
                        errors_writer.writerow(
                            {
                                "worker_index": self.args.worker_index,
                                "target_global": global_target,
                                "phase": phase,
                                "error": error,
                                "count": count,
                            }
                        )

                summary_writer.writerow(
                    {
                        "worker_index": self.args.worker_index,
                        "worker_count": self.args.worker_count,
                        "capacity_mode": self.args.capacity_mode,
                        "target_global": global_target,
                        "target_worker": worker_target,
                        "attempted": worker_target,
                        "established": established,
                        "establish_failed": worker_target - established,
                        "surviving": surviving,
                        "survival_failed": established - surviving,
                        "ramp_elapsed_seconds": f"{ramp_elapsed:.6f}",
                        "established_per_second": f"{(established / ramp_elapsed) if ramp_elapsed else 0:.6f}",
                        "level_elapsed_seconds": f"{time.perf_counter() - level_started:.6f}",
                    }
                )
                summary_file.flush()
                latency_file.flush()
                errors_file.flush()

                self.close_all(connections)
                if level_index + 1 < len(levels) and self.args.inter_level_cooldown_seconds > 0:
                    await asyncio.sleep(self.args.inter_level_cooldown_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Distributed Octavia concurrent-connection capacity worker")
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--path", default="/1024.bin")
    parser.add_argument("--capacity-mode", choices=["idle", "active"], required=True)
    parser.add_argument("--levels", required=True, help="comma-separated global connection targets")
    parser.add_argument("--worker-index", type=int, required=True)
    parser.add_argument("--worker-count", type=int, required=True)
    parser.add_argument("--ramp-seconds", type=float, default=30)
    parser.add_argument("--hold-seconds", type=float, default=60)
    parser.add_argument("--heartbeat-seconds", type=float, default=10)
    parser.add_argument("--inter-level-cooldown-seconds", type=float, default=10)
    parser.add_argument("--connect-timeout", type=float, default=10)
    parser.add_argument("--request-timeout", type=float, default=10)
    parser.add_argument("--open-concurrency", type=int, default=512)
    parser.add_argument("--io-concurrency", type=int, default=1024)
    parser.add_argument("--start-epoch", type=float, default=0)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-prefix", default="")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--abortive-close", action="store_true")
    parser.add_argument("--verify-idle-at-end", action="store_true")
    parser.add_argument("--skip-final-heartbeat", action="store_true")
    parser.add_argument("--tcp-nodelay", action="store_true")
    args = parser.parse_args()
    args.levels = [int(x.strip()) for x in args.levels.split(",") if x.strip()]
    if not args.levels or any(x <= 0 for x in args.levels):
        parser.error("--levels must contain positive integers")
    if args.worker_count < 1 or not 0 <= args.worker_index < args.worker_count:
        parser.error("worker index/count are inconsistent")
    for name in ("open_concurrency", "io_concurrency"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be >= 1")
    return args


async def amain() -> None:
    args = parse_args()
    print(
        "connection-capacity startup: "
        f"target={args.target_url} mode={args.capacity_mode} "
        f"insecure={args.insecure} worker={args.worker_index}/{args.worker_count} "
        f"levels={','.join(str(x) for x in args.levels)}",
        flush=True,
    )
    runner = CapacityRunner(args)
    if runner.ssl_context is not None:
        print(
            "TLS context: "
            f"verify_mode={runner.ssl_context.verify_mode} "
            f"check_hostname={runner.ssl_context.check_hostname}",
            flush=True,
        )
    await runner.run()


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        raise SystemExit(130)
