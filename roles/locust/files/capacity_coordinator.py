#!/usr/bin/env python3
"""Small TCP barrier coordinator for distributed connection-capacity tests."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from typing import Any


class BarrierCoordinator:
    def __init__(self, run_id: str, worker_count: int, timeout_seconds: float) -> None:
        if worker_count < 1:
            raise ValueError("worker_count must be >= 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        self.run_id = run_id
        self.worker_count = worker_count
        self.timeout_seconds = timeout_seconds
        self.condition = asyncio.Condition()
        self.arrivals: dict[tuple[str, int], set[int]] = defaultdict(set)
        self.started_at = time.monotonic()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not raw:
                return
            request: Any = json.loads(raw.decode("utf-8"))
            if request.get("run_id") != self.run_id:
                await self.respond(writer, {"status": "error", "error": "run_id_mismatch"})
                return
            try:
                worker_index = int(request["worker_index"])
                level = int(request["level"])
                phase = str(request["phase"])
            except (KeyError, TypeError, ValueError):
                await self.respond(writer, {"status": "error", "error": "invalid_worker_level_or_phase"})
                return
            if phase not in {"ready", "verified"}:
                await self.respond(writer, {"status": "error", "error": "invalid_barrier_phase"})
                return
            if not 0 <= worker_index < self.worker_count or level <= 0:
                await self.respond(writer, {"status": "error", "error": "worker_or_level_out_of_range"})
                return

            key = (phase, level)
            async with self.condition:
                arrived = self.arrivals[key]
                arrived.add(worker_index)
                count = len(arrived)
                print(
                    f"barrier arrival phase={phase} level={level} workers={count}/{self.worker_count}",
                    flush=True,
                )
                self.condition.notify_all()
                try:
                    await asyncio.wait_for(
                        self.condition.wait_for(
                            lambda: len(self.arrivals[key]) >= self.worker_count
                        ),
                        timeout=self.timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    await self.respond(
                        writer,
                        {
                            "status": "error",
                            "error": "barrier_timeout",
                            "phase": phase,
                            "level": level,
                            "arrived": sorted(self.arrivals[key]),
                            "expected": self.worker_count,
                        },
                    )
                    print(
                        f"barrier timeout phase={phase} level={level} workers={len(self.arrivals[key])}/{self.worker_count}",
                        flush=True,
                    )
                    return

            await self.respond(writer, {"status": "go", "phase": phase, "level": level})
            print(f"barrier released phase={phase} level={level}", flush=True)
        except (asyncio.TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            try:
                await self.respond(writer, {"status": "error", "error": type(exc).__name__})
            except Exception:
                pass
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    async def respond(writer: asyncio.StreamWriter, data: dict[str, Any]) -> None:
        writer.write(json.dumps(data, separators=(",", ":")).encode("utf-8") + b"\n")
        await writer.drain()

    async def serve(self, bind: str, port: int, ready_file: str | None) -> None:
        server = await asyncio.start_server(self.handle, bind, port, reuse_address=True)
        if ready_file:
            with open(ready_file, "w", encoding="utf-8") as stream:
                stream.write(f"{port}\n")
        sockets = server.sockets or []
        bound = ",".join(str(sock.getsockname()) for sock in sockets)
        print(
            f"capacity coordinator ready run_id={self.run_id} workers={self.worker_count} bind={bound}",
            flush=True,
        )
        async with server:
            await server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5557)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--worker-count", type=int, required=True)
    parser.add_argument("--barrier-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--ready-file")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    return args


async def amain() -> None:
    args = parse_args()
    coordinator = BarrierCoordinator(
        args.run_id, args.worker_count, args.barrier_timeout_seconds
    )
    await coordinator.serve(args.bind, args.port, args.ready_file)


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        raise SystemExit(130)
