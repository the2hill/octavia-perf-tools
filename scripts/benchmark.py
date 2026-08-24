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

from topology import direct_backend_reachable, resolved_generator_network_mode

ROOT = pathlib.Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / ".venv" / "bin" / "ansible-playbook"
PYTHON = ROOT / ".venv" / "bin" / "python"


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "default"


def ansible(playbook: str, config: pathlib.Path, **extra: str) -> None:
    cmd = [str(ANSIBLE), playbook, "-e", f"@{config}"]
    for key, value in extra.items():
        cmd.extend(["-e", f"{key}={value}"])
    run(*cmd)


def one_run(
    config: pathlib.Path,
    flavor: str,
    scenario_name: str,
    target_kind: str,
    repetition: int,
) -> pathlib.Path:
    orchestration_started = dt.datetime.now(dt.timezone.utc)
    stamp = orchestration_started.strftime("%Y%m%dT%H%M%SZ")
    bench_id = (
        f"{stamp}-{slug(scenario_name)}-{slug(flavor)}-{target_kind}-r{repetition:02d}"
    )
    result_dir = ROOT / "results" / bench_id
    result_dir.mkdir(parents=True, exist_ok=False)

    common = {
        "octavia_flavor": flavor,
        "scenario_name": scenario_name,
        "benchmark_id": bench_id,
    }
    try:
        if target_kind == "octavia":
            ansible("playbooks/create_lb.yml", config, **common)
        elif target_kind == "direct":
            ansible("playbooks/set_direct_target.yml", config, **common)
        else:
            raise ValueError(target_kind)

        load_started = dt.datetime.now(dt.timezone.utc)
        ansible("playbooks/run_test.yml", config, **common)
        load_completed = dt.datetime.now(dt.timezone.utc)
        timing = {
            "orchestration_started_at_utc": orchestration_started.replace(microsecond=0).isoformat(),
            "load_test_started_at_utc": load_started.replace(microsecond=0).isoformat(),
            "load_test_completed_at_utc": load_completed.replace(microsecond=0).isoformat(),
            "load_test_elapsed_seconds": round((load_completed - load_started).total_seconds(), 3),
        }
        (result_dir / "timing.yml").write_text(yaml.safe_dump(timing, sort_keys=False))
        ansible("playbooks/collect.yml", config, **common)
        run(str(PYTHON), "scripts/manifest.py", str(result_dir))
        run(str(PYTHON), "scripts/report.py", str(result_dir))
    finally:
        if target_kind == "octavia":
            # Deterministic naming lets this clean up even after partial creation.
            ansible("playbooks/destroy_lb.yml", config, **common)
    return result_dir


def selected_scenarios(cfg: dict[str, Any], overrides: list[str] | None) -> list[str]:
    scenario_cfg = cfg.get("scenarios") or {}
    catalog = scenario_cfg.get("catalog") or {}
    names = overrides or [str(x) for x in scenario_cfg.get("enabled") or []]
    missing = [name for name in names if name not in catalog]
    if missing:
        raise SystemExit(f"unknown scenario(s): {', '.join(missing)}")
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the configured Octavia performance scenario matrix")
    parser.add_argument("--config", default="config/local.yml")
    parser.add_argument("--flavor", action="append", help="override configured flavor(s); may repeat")
    parser.add_argument("--scenario", action="append", help="override enabled scenario(s); may repeat")
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--repetitions", type=int, help="override campaign.repetitions")
    args = parser.parse_args()

    config = pathlib.Path(args.config)
    if not config.is_absolute():
        config = ROOT / config
    cfg = yaml.safe_load(config.read_text())
    flavors = args.flavor or [str(x) for x in cfg["octavia"]["flavors"]]
    scenario_names = selected_scenarios(cfg, args.scenario)
    catalog = cfg["scenarios"]["catalog"]
    selected_tls = [
        name
        for name in scenario_names
        if (catalog[name] or {}).get("scheme") == "https"
        or bool((catalog[name] or {}).get("frontend_tls_termination", False))
        or bool((catalog[name] or {}).get("backend_tls", False))
    ]
    if selected_tls and not bool((cfg.get("tls") or {}).get("enabled", False)):
        raise SystemExit(
            "selected scenario(s) require TLS but tls.enabled=false: " + ", ".join(selected_tls)
        )
    campaign = cfg.get("campaign", {})
    repetitions = int(args.repetitions or campaign.get("repetitions", 3))
    baseline_repetitions = int(campaign.get("baseline_repetitions", 1))
    cooldown = float(campaign.get("cooldown_seconds", 15))

    run(str(PYTHON), "scripts/validate_config.py", str(config))

    outputs: list[pathlib.Path] = []
    first = True

    def cool_down() -> None:
        nonlocal first
        if not first and cooldown > 0:
            print(f"Cooldown between benchmark runs: {cooldown:g}s", flush=True)
            time.sleep(cooldown)
        first = False

    if cfg["locust"].get("baseline_direct", True) and not args.skip_baseline:
        if not direct_backend_reachable(cfg):
            print(
                "Skipping direct-to-backend baseline: generator topology "
                f"{resolved_generator_network_mode(cfg)} intentionally has no private route to backends.",
                flush=True,
            )
        else:
            baseline_scenarios = [
                name for name in scenario_names if bool((catalog[name] or {}).get("direct_baseline", False))
            ]
            for scenario_name in baseline_scenarios:
                for rep in range(1, baseline_repetitions + 1):
                    cool_down()
                    outputs.append(one_run(config, "baseline", scenario_name, "direct", rep))

    schedule = [
        (flavor, scenario_name, rep)
        for rep in range(1, repetitions + 1)
        for flavor in flavors
        for scenario_name in scenario_names
    ]
    if campaign.get("randomize_run_order", campaign.get("randomize_flavor_order", True)):
        random.shuffle(schedule)

    for flavor, scenario_name, rep in schedule:
        cool_down()
        outputs.append(one_run(config, flavor, scenario_name, "octavia", rep))

    run(str(PYTHON), "scripts/compare.py", str(ROOT / "results"))
    print("\nCompleted:")
    for out in outputs:
        print(f"  {out.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
