#!/usr/bin/env python3
"""Install/restore a narrow controller route for an OpenStack management FIP.

The benchmark controller may itself live on a jumbo-MTU tenant network while the
external/FIP network is 1500 bytes.  A host route with the external network MTU
keeps SSH/Ansible control traffic from relying on broken PMTU signalling without
changing the controller interface MTU or benchmark east-west traffic.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def route_get(destination: str) -> dict[str, str]:
    cp = run("ip", "-4", "route", "get", destination)
    line = cp.stdout.strip().splitlines()[0]
    tokens = shlex.split(line)
    data: dict[str, str] = {"raw": line}
    for key in ("via", "dev", "src", "table"):
        if key in tokens:
            idx = tokens.index(key)
            if idx + 1 < len(tokens):
                data[key] = tokens[idx + 1]
    if "dev" not in data:
        raise RuntimeError(f"could not determine route device from: {line}")
    return data


def exact_host_route(destination: str) -> str | None:
    prefix = f"{destination}/32"
    cp = run("ip", "-4", "route", "show", "table", "main", check=False)
    for line in cp.stdout.splitlines():
        if line.split() and line.split()[0] == prefix:
            return line.strip()
    return None


def ensure(destination: str, mtu: int, state_file: Path) -> None:
    if os.geteuid() != 0:
        raise RuntimeError("route installation requires root; run through Ansible become/sudo")
    if not 576 <= mtu <= 65535:
        raise RuntimeError(f"invalid MTU: {mtu}")

    existing_state = None
    if state_file.exists():
        try:
            existing_state = json.loads(state_file.read_text())
        except (OSError, ValueError, TypeError):
            existing_state = None
        if existing_state and str(existing_state.get("destination")) != destination:
            restore(state_file)
            existing_state = None

    current = route_get(destination)
    previous = (
        existing_state.get("previous_exact_route")
        if existing_state and str(existing_state.get("destination")) == destination
        else exact_host_route(destination)
    )
    route_before = (
        existing_state.get("route_before")
        if existing_state and str(existing_state.get("destination")) == destination
        else current.get("raw")
    )
    advmss = max(536, mtu - 40)

    cmd = ["ip", "-4", "route", "replace", f"{destination}/32"]
    if current.get("via"):
        cmd += ["via", current["via"]]
    cmd += ["dev", current["dev"]]
    if current.get("src"):
        cmd += ["src", current["src"]]
    cmd += ["mtu", str(mtu), "advmss", str(advmss)]
    run(*cmd)

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "destination": destination,
        "mtu": mtu,
        "advmss": advmss,
        "device": current.get("dev"),
        "gateway": current.get("via"),
        "source": current.get("src"),
        "previous_exact_route": previous,
        "route_before": route_before,
        "route_after": route_get(destination).get("raw"),
    }
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.chmod(state_file, 0o600)
    print(json.dumps(state, sort_keys=True))


def restore(state_file: Path) -> None:
    if not state_file.exists():
        print(json.dumps({"changed": False, "reason": "state file absent"}))
        return
    if os.geteuid() != 0:
        raise RuntimeError("route restoration requires root; run through Ansible become/sudo")

    state = json.loads(state_file.read_text())
    destination = str(state["destination"])
    previous = state.get("previous_exact_route")
    if previous:
        tokens = shlex.split(previous)
        run("ip", "-4", "route", "replace", *tokens)
    else:
        run("ip", "-4", "route", "del", f"{destination}/32", check=False)
    state_file.unlink(missing_ok=True)
    print(json.dumps({"changed": True, "destination": destination, "restored_previous": bool(previous)}))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_ensure = sub.add_parser("ensure")
    p_ensure.add_argument("--destination", required=True)
    p_ensure.add_argument("--mtu", required=True, type=int)
    p_ensure.add_argument("--state-file", required=True, type=Path)

    p_restore = sub.add_parser("restore")
    p_restore.add_argument("--state-file", required=True, type=Path)

    args = parser.parse_args()
    try:
        if args.command == "ensure":
            ensure(args.destination, args.mtu, args.state_file)
        else:
            restore(args.state_file)
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        print(f"controller_fip_route: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

