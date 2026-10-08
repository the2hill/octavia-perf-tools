#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import random
import re
import subprocess
import time
from typing import Any

import yaml

from openstack_auth import connect as openstack_connect
from topology import direct_backend_reachable, resolved_generator_network_mode

ROOT = pathlib.Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / ".venv" / "bin" / "ansible-playbook"
PYTHON = ROOT / ".venv" / "bin" / "python"


def run(*args: str, log_path: pathlib.Path | None = None) -> None:
    print("+", " ".join(args), flush=True)
    if log_path is None:
        subprocess.run(args, cwd=ROOT, check=True)
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            args,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        returncode = proc.wait()
    if returncode:
        raise subprocess.CalledProcessError(returncode, args)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "default"


def ansible(
    playbook: str,
    config: pathlib.Path,
    *,
    log_path: pathlib.Path | None = None,
    **extra: str,
) -> None:
    cmd = [str(ANSIBLE), playbook, "-e", f"@{config}"]
    for key, value in extra.items():
        cmd.extend(["-e", f"{key}={value}"])
    run(*cmd, log_path=log_path)


def write_run_failure(
    result_dir: pathlib.Path,
    *,
    stage: str,
    exc: subprocess.CalledProcessError,
) -> None:
    failure = {
        "failed_at_utc": dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "stage": stage,
        "returncode": exc.returncode,
        "command": [str(x) for x in (exc.cmd if isinstance(exc.cmd, (list, tuple)) else [exc.cmd])],
    }
    (result_dir / "RUN_FAILED.yml").write_text(
        yaml.safe_dump(failure, sort_keys=False), encoding="utf-8"
    )


def generate_report_best_effort(result_dir: pathlib.Path) -> bool:
    """Generate reporting artifacts without reclassifying a completed load test as failed."""
    try:
        run(str(PYTHON), "scripts/report.py", str(result_dir))
        return True
    except subprocess.CalledProcessError as exc:
        failure = {
            "failed_at_utc": dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "stage": "report",
            "returncode": exc.returncode,
