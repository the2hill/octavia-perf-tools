from __future__ import annotations

import csv
import json
import math
import os
import time
from pathlib import Path

from locust import FastHttpUser, LoadTestShape, constant, task

PATH = os.environ.get("OCTAVIA_PERF_PATH", "/1024.bin")
STAGES = json.loads(os.environ.get("OCTAVIA_PERF_STAGES", "[]"))
CONNECTION_MODE = os.environ.get("OCTAVIA_PERF_CONNECTION_MODE", "keepalive").lower()
PROFILE = os.environ.get("OCTAVIA_PERF_LOCUST_PROFILE", "staircase").lower()
MAX_RPS = json.loads(os.environ.get("OCTAVIA_PERF_MAX_RPS", "{}"))
MAX_RPS_OUTPUT = os.environ.get("OCTAVIA_PERF_MAX_RPS_OUTPUT", "")


class OctaviaUser(FastHttpUser):
    wait_time = constant(0)
    connection_timeout = float(os.environ.get("OCTAVIA_PERF_TIMEOUT", "10"))
    network_timeout = float(os.environ.get("OCTAVIA_PERF_TIMEOUT", "10"))
    # FastHttpUser defaults to insecure=True, which is deliberate for generated
    # benchmark certificates. Certificate verification can be enabled by changing
    # this environment value to false before the worker process starts.
    insecure = os.environ.get("OCTAVIA_PERF_TLS_INSECURE", "true").lower() in ("1", "true", "yes", "on")

    @task
    def request_payload(self):
        headers = {"Connection": "close"} if CONNECTION_MODE == "close" else None
        with self.client.get(PATH, name=PATH, headers=headers, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"unexpected HTTP {response.status_code}")


def _percentile_from_histogram(histogram: dict[int, int], percentile: float) -> float | None:
    total = sum(max(0, int(v)) for v in histogram.values())
    if total <= 0:
        return None
    rank = max(1, math.ceil(total * percentile))
    seen = 0
    for value in sorted(histogram):
        seen += max(0, int(histogram[value]))
        if seen >= rank:
            return float(value)
    return float(max(histogram))


class BenchmarkShape(LoadTestShape):
    """Normal fixed staircase or an adaptive max-sustainable-RPS search."""

    def __init__(self) -> None:
        super().__init__()
        self.profile = PROFILE
        self.target_users = max(1, int(MAX_RPS.get("start_users", 500)))
        self.spawn_rate = max(1.0, float(MAX_RPS.get("spawn_rate", 4000)))
        self.max_users = max(self.target_users, int(MAX_RPS.get("max_users", 64000)))
        self.growth_factor = max(1.1, float(MAX_RPS.get("growth_factor", 2.0)))
        self.settle_seconds = max(0.0, float(MAX_RPS.get("settle_seconds", 10)))
        self.measure_seconds = max(1.0, float(MAX_RPS.get("measure_seconds", 45)))
        self.failure_threshold = max(0.0, float(MAX_RPS.get("failure_threshold_percent", 1.0)))
        self.p99_max_ms = float(MAX_RPS.get("p99_max_ms", 1000))
        self.resolution_users = max(1, int(MAX_RPS.get("search_resolution_users", 250)))
        self.max_steps = max(1, int(MAX_RPS.get("max_search_steps", 16)))
        self.reach_tolerance_percent = max(0.0, float(MAX_RPS.get("user_reach_tolerance_percent", 2.0)))
        self.user_reach_timeout_seconds = max(1.0, float(MAX_RPS.get("user_reach_timeout_seconds", 60.0)))
        self.lower_users = 0
        self.upper_users: int | None = None
        self.step = 0
        self.ready_since: float | None = None
        self.target_assigned_at: float | None = None
        self.measure_started: float | None = None
        self.snapshot: dict | None = None
        self.done = False
        self.seen_targets: set[int] = set()
        self.output_path = Path(MAX_RPS_OUTPUT) if MAX_RPS_OUTPUT else None
        if self.profile == "max_rps" and self.output_path:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with self.output_path.open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=self._fieldnames())
                writer.writeheader()

    @staticmethod
    def _fieldnames() -> list[str]:
        return [
            "step",
            "target_users",
            "actual_users",
            "measure_seconds",
            "requests",
            "failures",
            "failure_percent",
            "average_rps",
            "average_response_ms",
            "p99_ms",
            "passed",
            "failure_reasons",
            "lower_users_after",
            "upper_users_after",
        ]

    def _normal_tick(self):
        if not STAGES:
            return None
        elapsed = self.get_run_time()
        boundary = 0
        for stage in STAGES:
            boundary += int(stage["duration_seconds"])
            if elapsed < boundary:
                return int(stage["users"]), float(stage["spawn_rate"])
        return None

    def _stats_snapshot(self) -> dict:
        total = self.runner.stats.total
        return {
            "requests": int(total.num_requests),
            "failures": int(total.num_failures),
            "response_time_total": float(total.total_response_time),
            "response_times": {int(k): int(v) for k, v in total.response_times.items()},
        }

    @staticmethod
    def _histogram_delta(current: dict[int, int], previous: dict[int, int]) -> dict[int, int]:
        keys = set(current) | set(previous)
        return {k: max(0, int(current.get(k, 0)) - int(previous.get(k, 0))) for k in keys}

    def _write_stage(self, row: dict) -> None:
        print("MAX_RPS_STAGE " + json.dumps(row, sort_keys=True), flush=True)
        if not self.output_path:
            return
        with self.output_path.open("a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=self._fieldnames())
            writer.writerow(row)

    def _next_midpoint(self) -> int | None:
        if self.upper_users is None:
            candidate = min(self.max_users, max(self.target_users + 1, int(math.ceil(self.target_users * self.growth_factor))))
            return None if candidate == self.target_users else candidate
        if self.lower_users <= 0:
            candidate = max(1, self.upper_users // 2)
            return None if candidate == self.target_users else candidate
        if self.upper_users - self.lower_users <= self.resolution_users:
            return None
        candidate = (self.lower_users + self.upper_users) // 2
        if candidate <= self.lower_users:
            candidate = self.lower_users + 1
        if candidate >= self.upper_users:
            candidate = self.upper_users - 1
        return candidate if candidate > 0 else None

    def _reset_stage(self, next_target: int) -> None:
        self.target_users = min(self.max_users, max(1, int(next_target)))
        self.ready_since = None
        self.target_assigned_at = time.monotonic()
        self.measure_started = None
        self.snapshot = None

    def _evaluate(self, now: float, actual_users: int) -> None:
        current = self._stats_snapshot()
        previous = self.snapshot or current
        measure_started = self.measure_started if self.measure_started is not None else now
        elapsed = max(0.001, now - float(measure_started))
        requests = max(0, current["requests"] - previous["requests"])
        failures = max(0, current["failures"] - previous["failures"])
        failure_percent = (failures / requests * 100.0) if requests else 100.0
        response_total = max(0.0, current["response_time_total"] - previous["response_time_total"])
        avg_ms = response_total / requests if requests else None
        hist = self._histogram_delta(current["response_times"], previous["response_times"])
        p99_ms = _percentile_from_histogram(hist, 0.99)
        average_rps = requests / elapsed

        reasons: list[str] = []
        if requests <= 0:
            reasons.append("no_requests")
        if failure_percent > self.failure_threshold:
            reasons.append("failure_rate")
        if self.p99_max_ms > 0 and (p99_ms is None or p99_ms > self.p99_max_ms):
            reasons.append("p99_latency")
        passed = not reasons

        if passed:
            self.lower_users = max(self.lower_users, self.target_users)
        else:
            self.upper_users = self.target_users if self.upper_users is None else min(self.upper_users, self.target_users)

        self.step += 1
        row = {
            "step": self.step,
            "target_users": self.target_users,
            "actual_users": actual_users,
            "measure_seconds": round(elapsed, 3),
            "requests": requests,
            "failures": failures,
            "failure_percent": round(failure_percent, 6),
            "average_rps": round(average_rps, 6),
            "average_response_ms": round(avg_ms, 6) if avg_ms is not None else "",
            "p99_ms": round(p99_ms, 6) if p99_ms is not None else "",
            "passed": str(passed).lower(),
            "failure_reasons": ";".join(reasons),
            "lower_users_after": self.lower_users,
            "upper_users_after": self.upper_users if self.upper_users is not None else "",
        }
        self._write_stage(row)

        if self.step >= self.max_steps:
            self.done = True
            return
        if passed and self.target_users >= self.max_users and self.upper_users is None:
            self.done = True
            return
        next_target = self._next_midpoint()
        if next_target is None or next_target in self.seen_targets:
            self.done = True
            return
        self.seen_targets.add(self.target_users)
        self._reset_stage(next_target)

    def _record_user_reach_failure(self, actual_users: int) -> None:
        self.upper_users = self.target_users if self.upper_users is None else min(self.upper_users, self.target_users)
        self.step += 1
        row = {
            "step": self.step,
            "target_users": self.target_users,
            "actual_users": actual_users,
            "measure_seconds": 0.0,
            "requests": 0,
            "failures": 0,
            "failure_percent": 100.0,
            "average_rps": 0.0,
            "average_response_ms": "",
            "p99_ms": "",
            "passed": "false",
            "failure_reasons": "user_reach_timeout",
            "lower_users_after": self.lower_users,
            "upper_users_after": self.upper_users,
        }
        self._write_stage(row)
        if self.step >= self.max_steps:
            self.done = True
            return
        next_target = self._next_midpoint()
        if next_target is None or next_target in self.seen_targets:
            self.done = True
            return
        self.seen_targets.add(self.target_users)
        self._reset_stage(next_target)

    def _max_rps_tick(self):
        if self.done:
            return None
        if self.runner is None:
            return self.target_users, self.spawn_rate

        now = time.monotonic()
        if self.target_assigned_at is None:
            self.target_assigned_at = now
        actual_users = int(self.get_current_user_count())
        tolerance = max(1, int(math.ceil(self.target_users * self.reach_tolerance_percent / 100.0)))
        if abs(actual_users - self.target_users) > tolerance:
            self.ready_since = None
            self.measure_started = None
            self.snapshot = None
            if now - float(self.target_assigned_at) >= self.user_reach_timeout_seconds:
                self._record_user_reach_failure(actual_users)
                return None if self.done else (self.target_users, self.spawn_rate)
            return self.target_users, self.spawn_rate

        if self.ready_since is None:
            self.ready_since = now
            return self.target_users, self.spawn_rate
        if now - self.ready_since < self.settle_seconds:
            return self.target_users, self.spawn_rate

        if self.measure_started is None:
            self.measure_started = now
            self.snapshot = self._stats_snapshot()
            return self.target_users, self.spawn_rate
        if now - self.measure_started < self.measure_seconds:
            return self.target_users, self.spawn_rate

        self._evaluate(now, actual_users)
        return None if self.done else (self.target_users, self.spawn_rate)

    def tick(self):
        if self.profile == "max_rps":
            return self._max_rps_tick()
        return self._normal_tick()
