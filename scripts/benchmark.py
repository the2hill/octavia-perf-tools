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


def collect_lb_failure_diagnostics(
    config: pathlib.Path,
    *,
    lb_name: str,
    attempt: int,
    result_dir: pathlib.Path,
) -> None:
    output = result_dir / "orchestration" / f"lb-create-attempt-{attempt:02d}-diagnostics.json"
    cmd = [
        str(PYTHON),
        "scripts/lb_failure_diagnostics.py",
        "--config",
        str(config),
        "--load-balancer",
        lb_name,
        "--output",
        str(output),
    ]
    try:
        run(*cmd)
    except subprocess.CalledProcessError as diag_exc:
        print(
            "WARNING: failed to collect complete load-balancer diagnostics "
            f"(rc={diag_exc.returncode}); continuing with cleanup/retry.",
            flush=True,
        )


def cleanup_failed_lb(
    config: pathlib.Path,
    common: dict[str, str],
    *,
    lb_name: str,
    attempt: int,
    result_dir: pathlib.Path,
) -> bool:
    cleanup_log = result_dir / "orchestration" / f"lb-create-attempt-{attempt:02d}-cleanup.log"
    try:
        ansible("playbooks/destroy_lb.yml", config, log_path=cleanup_log, **common)
    except subprocess.CalledProcessError as cleanup_exc:
        print(
            "WARNING: cleanup after failed load-balancer provisioning returned "
            f"rc={cleanup_exc.returncode}; retry may fail if the old LB still exists.",
            flush=True,
        )
        return False

    verify_output = (
        result_dir
        / "orchestration"
        / f"lb-create-attempt-{attempt:02d}-post-cleanup.json"
    )
    try:
        run(
            str(PYTHON),
            "scripts/lb_failure_diagnostics.py",
            "--config",
            str(config),
            "--load-balancer",
            lb_name,
            "--output",
            str(verify_output),
            "--assert-absent",
        )
        return True
    except subprocess.CalledProcessError:
        print(
            f"WARNING: load balancer {lb_name} still exists after cleanup.",
            flush=True,
        )
        return False


def one_run(
    config: pathlib.Path,
    flavor: str,
    scenario_name: str,
    target_kind: str,
    repetition: int,
    *,
    lb_create_attempts: int = 1,
    lb_create_retry_delay_seconds: float = 0,
    reuse_campaign_lb: bool = False,
    campaign_id: str | None = None,
    suite_id: str | None = None,
    baseline_for_flavor: str | None = None,
) -> pathlib.Path:
    orchestration_started = dt.datetime.now(dt.timezone.utc)
    stamp = orchestration_started.strftime("%Y%m%dT%H%M%SZ")
    result_flavor_label = baseline_for_flavor if target_kind == "direct" and baseline_for_flavor else flavor
    bench_id = (
        f"{stamp}-{slug(scenario_name)}-{slug(result_flavor_label)}-{target_kind}-r{repetition:02d}"
    )
    result_dir = ROOT / "results" / bench_id
    result_dir.mkdir(parents=True, exist_ok=False)

    common = {
        "octavia_flavor": flavor,
        "scenario_name": scenario_name,
        "benchmark_id": bench_id,
    }
    if campaign_id is not None:
        common["campaign_id"] = campaign_id
    if suite_id is not None:
        common["suite_id"] = suite_id
    if baseline_for_flavor is not None:
        common["baseline_for_flavor"] = baseline_for_flavor
    stage = "initialization"
    cleanup_needed = False
    try:
        if target_kind == "octavia" and reuse_campaign_lb:
            if campaign_id is None:
                raise ValueError("campaign_id is required when reuse_campaign_lb=True")
            stage = "configure_campaign_lb_scenario"
            cleanup_needed = True
            print(
                f"Reusing persistent campaign LB {campaign_lb_name(config, flavor, campaign_id)} "
                f"for scenario {scenario_name} r{repetition:02d}",
                flush=True,
            )
            ansible("playbooks/configure_campaign_lb_scenario.yml", config, **common)
        elif target_kind == "octavia":
            lb_name = (
                f"{cfg_run_prefix(config)}-{slug(flavor)}-{slug(scenario_name)}"
            )
            create_succeeded = False
            for attempt in range(1, lb_create_attempts + 1):
                stage = f"create_lb_attempt_{attempt}"
                create_log = (
                    result_dir
                    / "orchestration"
                    / f"lb-create-attempt-{attempt:02d}.log"
                )
                print(
                    f"Load-balancer provisioning attempt {attempt}/{lb_create_attempts}: "
                    f"{lb_name}",
                    flush=True,
                )
                try:
                    cleanup_needed = True
                    ansible(
                        "playbooks/create_lb.yml",
                        config,
                        log_path=create_log,
                        **common,
                    )
                    create_succeeded = True
                    break
                except subprocess.CalledProcessError as create_exc:
                    print(
                        f"WARNING: load-balancer provisioning attempt {attempt} failed "
                        f"(rc={create_exc.returncode}). Collecting diagnostics before cleanup.",
                        flush=True,
                    )
                    collect_lb_failure_diagnostics(
                        config,
                        lb_name=lb_name,
                        attempt=attempt,
                        result_dir=result_dir,
                    )
                    cleanup_ok = cleanup_failed_lb(
                        config,
                        common,
                        lb_name=lb_name,
                        attempt=attempt,
                        result_dir=result_dir,
                    )
                    cleanup_needed = not cleanup_ok
                    if attempt >= lb_create_attempts:
                        raise
                    if lb_create_retry_delay_seconds > 0:
                        print(
                            "Retrying load-balancer provisioning after "
                            f"{lb_create_retry_delay_seconds:g}s...",
                            flush=True,
                        )
                        time.sleep(lb_create_retry_delay_seconds)
            if not create_succeeded:
                raise RuntimeError("load-balancer provisioning did not succeed")
        elif target_kind == "direct":
            stage = "set_direct_target"
            ansible("playbooks/set_direct_target.yml", config, **common)
        else:
            raise ValueError(target_kind)

        stage = "run_test"
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
        stage = "collect"
        ansible("playbooks/collect.yml", config, **common)
        stage = "manifest"
        run(str(PYTHON), "scripts/manifest.py", str(result_dir))
        stage = "report"
        run(str(PYTHON), "scripts/report.py", str(result_dir))
    except subprocess.CalledProcessError as exc:
        write_run_failure(result_dir, stage=stage, exc=exc)
        if target_kind == "octavia" and reuse_campaign_lb and campaign_id is not None:
            try:
                collect_lb_failure_diagnostics(
                    config,
                    lb_name=campaign_lb_name(config, flavor, campaign_id),
                    attempt=1,
                    result_dir=result_dir,
                )
            except Exception as diag_exc:
                print(f"WARNING: persistent LB diagnostics failed: {diag_exc}", flush=True)
        raise
    finally:
        if target_kind == "octavia" and cleanup_needed:
            try:
                if reuse_campaign_lb:
                    ansible("playbooks/destroy_campaign_lb_scenario.yml", config, **common)
                else:
                    ansible("playbooks/destroy_lb.yml", config, **common)
            except subprocess.CalledProcessError as cleanup_exc:
                print(
                    "WARNING: final load-balancer cleanup failed "
                    f"(rc={cleanup_exc.returncode}).",
                    flush=True,
                )
    return result_dir


def cfg_run_prefix(config: pathlib.Path) -> str:
    cfg = yaml.safe_load(config.read_text()) or {}
    return str(cfg.get("run_prefix") or "octavia-perf")


def resolve_octavia_flavor(config: pathlib.Path, flavor: str) -> dict[str, Any] | None:
    """Resolve an Octavia flavor name/ID before LB creation.

    Passing the resolved UUID to the create playbook removes ambiguity and lets us
    verify that the immutable LB flavor_id is exactly the flavor requested for
    this suite.
    """
    if flavor == "default":
        return None

    try:
        import openstack
    except ImportError as exc:
        raise RuntimeError(
            "openstacksdk is required to resolve the Octavia flavor; run make bootstrap"
        ) from exc

    cfg = yaml.safe_load(config.read_text()) or {}
    cloud_cfg = cfg.get("openstack") or {}
    cloud = cloud_cfg.get("cloud")
    if not cloud:
        raise RuntimeError("openstack.cloud is required to resolve the Octavia flavor")

    connect_args: dict[str, Any] = {"cloud": cloud}
    region = cloud_cfg.get("region_name")
    if region:
        connect_args["region_name"] = region
    conn = openstack.connect(**connect_args)
    obj = conn.load_balancer.find_flavor(flavor, ignore_missing=True)
    if obj is None:
        raise RuntimeError(f"Octavia flavor {flavor!r} was not found")

    enabled = getattr(obj, "is_enabled", None)
    if enabled is None:
        enabled = getattr(obj, "enabled", None)
    if enabled is False:
        raise RuntimeError(
            f"Octavia flavor {flavor!r} ({obj.id}) is disabled; enable it for the initial LB create"
        )

    return {
        "id": str(obj.id),
        "name": str(getattr(obj, "name", None) or flavor),
        "is_enabled": enabled,
    }


def campaign_lb_name(config: pathlib.Path, flavor: str, campaign_id: str) -> str:
    return f"{cfg_run_prefix(config)}-{slug(flavor)}-campaign-{slug(campaign_id)}"


def campaign_lb_state_path(flavor: str, campaign_id: str) -> pathlib.Path:
    return ROOT / "state" / f"campaign_lb-{slug(flavor)}-{slug(campaign_id)}.yml"


def cleanup_failed_campaign_lb(
    config: pathlib.Path,
    *,
    flavor: str,
    campaign_id: str,
    lb_name: str,
    attempt: int,
    result_dir: pathlib.Path,
) -> bool:
    cleanup_log = result_dir / "orchestration" / f"lb-create-attempt-{attempt:02d}-cleanup.log"
    try:
        ansible(
            "playbooks/destroy_campaign_lb.yml",
            config,
            log_path=cleanup_log,
            octavia_flavor=flavor,
            campaign_id=campaign_id,
        )
    except subprocess.CalledProcessError as cleanup_exc:
        print(
            "WARNING: cleanup after failed persistent load-balancer provisioning returned "
            f"rc={cleanup_exc.returncode}; retry may fail if the old LB still exists.",
            flush=True,
        )
        return False

    verify_output = (
        result_dir
        / "orchestration"
        / f"lb-create-attempt-{attempt:02d}-post-cleanup.json"
    )
    try:
        run(
            str(PYTHON),
            "scripts/lb_failure_diagnostics.py",
            "--config",
            str(config),
            "--load-balancer",
            lb_name,
            "--output",
            str(verify_output),
            "--assert-absent",
        )
        return True
    except subprocess.CalledProcessError:
        print(f"WARNING: load balancer {lb_name} still exists after cleanup.", flush=True)
        return False


def prepare_campaign_lb(
    config: pathlib.Path,
    *,
    flavor: str,
    campaign_id: str,
    lb_create_attempts: int,
    lb_create_retry_delay_seconds: float,
) -> dict[str, Any]:
    resolved_flavor = resolve_octavia_flavor(config, flavor)
    resolved_flavor_id = resolved_flavor["id"] if resolved_flavor else ""
    if resolved_flavor:
        print(
            f"Resolved Octavia flavor: requested={flavor} name={resolved_flavor['name']} "
            f"id={resolved_flavor_id} enabled={resolved_flavor.get('is_enabled')}",
            flush=True,
        )
    else:
        print("Using Octavia/provider default flavor (no flavor_id requested).", flush=True)

    lb_name = campaign_lb_name(config, flavor, campaign_id)
    result_dir = ROOT / "results" / f"{slug(campaign_id)}-{slug(flavor)}-campaign-lb"
    result_dir.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, lb_create_attempts + 1):
        create_log = result_dir / "orchestration" / f"lb-create-attempt-{attempt:02d}.log"
        print(
            f"Persistent campaign LB provisioning attempt {attempt}/{lb_create_attempts}: {lb_name}",
            flush=True,
        )
        try:
            ansible(
                "playbooks/create_campaign_lb.yml",
                config,
                log_path=create_log,
                octavia_flavor=flavor,
                octavia_flavor_id=resolved_flavor_id,
                campaign_id=slug(campaign_id),
            )
            state_path = campaign_lb_state_path(flavor, campaign_id)
            state = yaml.safe_load(state_path.read_text()) or {}
            actual_flavor_id = str(state.get("flavor_id") or "")
            if resolved_flavor_id and actual_flavor_id != resolved_flavor_id:
                raise RuntimeError(
                    "Created load balancer flavor mismatch: "
                    f"requested {flavor} ({resolved_flavor_id}) but LB reports {actual_flavor_id or '<none>'}"
                )
            print("", flush=True)
            print("PERSISTENT OCTAVIA LOAD BALANCER READY", flush=True)
            print(f"  flavor: {flavor}", flush=True)
            print(f"  name:   {state.get('load_balancer_name', lb_name)}", flush=True)
            print(f"  id:     {state.get('load_balancer_id', '<unknown>')}", flush=True)
            print(f"  VIP:    {state.get('vip_address', '<unknown>')}", flush=True)
            print(
                "  This LB/amphora will be reused for all Octavia scenarios and repetitions.",
                flush=True,
            )
            print(
                "  The Octavia flavor may now be disabled; later scenario changes only replace child listener/pool resources.",
                flush=True,
            )
            return state
        except (subprocess.CalledProcessError, RuntimeError):
            print(
                f"WARNING: persistent campaign LB provisioning attempt {attempt} failed. "
                "Collecting diagnostics before cleanup.",
                flush=True,
            )
            collect_lb_failure_diagnostics(
                config, lb_name=lb_name, attempt=attempt, result_dir=result_dir
            )
            cleanup_ok = cleanup_failed_campaign_lb(
                config,
                flavor=flavor,
                campaign_id=campaign_id,
                lb_name=lb_name,
                attempt=attempt,
                result_dir=result_dir,
            )
            if attempt >= lb_create_attempts:
                raise
            if not cleanup_ok:
                print(
                    "WARNING: cleanup verification failed; the next provisioning attempt may collide with stale resources.",
                    flush=True,
                )
            if lb_create_retry_delay_seconds > 0:
                print(
                    "Retrying persistent load-balancer provisioning after "
                    f"{lb_create_retry_delay_seconds:g}s...",
                    flush=True,
                )
                time.sleep(lb_create_retry_delay_seconds)

    raise RuntimeError("persistent campaign load-balancer provisioning did not succeed")


def destroy_campaign_lb(config: pathlib.Path, *, flavor: str, campaign_id: str) -> None:
    try:
        ansible(
            "playbooks/destroy_campaign_lb.yml",
            config,
            octavia_flavor=flavor,
            campaign_id=campaign_id,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"WARNING: final persistent load-balancer cleanup failed for flavor {flavor} "
            f"(rc={exc.returncode}).",
            flush=True,
        )


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
    parser.add_argument(
        "--suite-id",
        help="stable identifier shared by the direct-control and Octavia phases of one baseline suite",
    )
    parser.add_argument(
        "--baseline-for-flavor",
        help="provenance tag for direct controls showing which flavor suite collected them",
    )
    parser.add_argument("--flavor", action="append", help="override configured flavor(s); may repeat")
    parser.add_argument("--scenario", action="append", help="override enabled scenario(s); may repeat")
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument(
        "--direct-baselines-only",
        action="store_true",
        help=(
            "run only selected scenarios marked direct_baseline=true; "
            "do not create Octavia load balancers"
        ),
    )
    parser.add_argument("--repetitions", type=int, help="override campaign.repetitions")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="record failed runs and continue with the remaining repetitions/scenarios",
    )
    parser.add_argument(
        "--lb-create-attempts",
        type=int,
        help="total load-balancer provisioning attempts per Octavia run",
    )
    parser.add_argument(
        "--lb-create-retry-delay-seconds",
        type=float,
        help="delay between failed load-balancer provisioning attempts",
    )
    parser.add_argument(
        "--reuse-load-balancer",
        action="store_true",
        help=(
            "create one persistent Octavia load balancer per flavor and reuse its amphora "
            "across all selected scenarios/repetitions; scenario listener/pool resources "
            "are recreated as needed"
        ),
    )
    parser.add_argument(
        "--pause-after-lb-create",
        action="store_true",
        help=(
            "with --reuse-load-balancer, pause after the persistent LB(s) are created so "
            "an operator can disable experimental flavors before benchmark traffic starts"
        ),
    )
    args = parser.parse_args()
    if args.skip_baseline and args.direct_baselines_only:
        parser.error("--skip-baseline and --direct-baselines-only are mutually exclusive")
    if args.pause_after_lb_create and not args.reuse_load_balancer:
        parser.error("--pause-after-lb-create requires --reuse-load-balancer")
    if args.direct_baselines_only and args.reuse_load_balancer:
        parser.error("--direct-baselines-only cannot be combined with --reuse-load-balancer")
    if args.baseline_for_flavor and not args.direct_baselines_only:
        parser.error("--baseline-for-flavor is only valid with --direct-baselines-only")

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
    lb_create_attempts = int(
        args.lb_create_attempts
        if args.lb_create_attempts is not None
        else campaign.get("lb_create_attempts", 1)
    )
    lb_create_retry_delay_seconds = float(
        args.lb_create_retry_delay_seconds
        if args.lb_create_retry_delay_seconds is not None
        else campaign.get("lb_create_retry_delay_seconds", 30)
    )
    if lb_create_attempts < 1:
        raise SystemExit("--lb-create-attempts must be >= 1")
    if lb_create_retry_delay_seconds < 0:
        raise SystemExit("--lb-create-retry-delay-seconds must be >= 0")

    run(str(PYTHON), "scripts/validate_config.py", str(config))

    outputs: list[pathlib.Path] = []
    failures: list[dict[str, Any]] = []
    campaign_id = slug(
        args.suite_id
        or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    prepared_campaign_flavors: set[str] = set()
    first = True

    def cool_down() -> None:
        nonlocal first
        if not first and cooldown > 0:
            print(f"Cooldown between benchmark runs: {cooldown:g}s", flush=True)
            time.sleep(cooldown)
        first = False

    def execute_run(
        flavor: str,
        scenario_name: str,
        target_kind: str,
        rep: int,
    ) -> None:
        try:
            outputs.append(
                one_run(
                    config,
                    flavor,
                    scenario_name,
                    target_kind,
                    rep,
                    lb_create_attempts=(lb_create_attempts if target_kind == "octavia" else 1),
                    lb_create_retry_delay_seconds=lb_create_retry_delay_seconds,
                    reuse_campaign_lb=(args.reuse_load_balancer and target_kind == "octavia"),
                    campaign_id=(campaign_id if args.reuse_load_balancer and target_kind == "octavia" else None),
                    suite_id=campaign_id,
                    baseline_for_flavor=(args.baseline_for_flavor if target_kind == "direct" else None),
                )
            )
        except subprocess.CalledProcessError as exc:
            failure = {
                "failed_at_utc": dt.datetime.now(dt.timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
                "target_kind": target_kind,
                "flavor": flavor,
                "scenario": scenario_name,
                "repetition": rep,
                "returncode": exc.returncode,
                "command": [
                    str(x)
                    for x in (
                        exc.cmd if isinstance(exc.cmd, (list, tuple)) else [exc.cmd]
                    )
                ],
            }
            failures.append(failure)
            print(
                "\nFAILED RUN: "
                f"target={target_kind} flavor={flavor} scenario={scenario_name} r{rep:02d} "
                f"rc={exc.returncode}",
                flush=True,
            )
            if not args.continue_on_error:
                raise
            print("Continuing with the remaining campaign runs.", flush=True)

    if cfg["locust"].get("baseline_direct", True) and not args.skip_baseline:
        if not direct_backend_reachable(cfg):
            print(
                "Skipping direct-to-backend baseline: generator topology "
                f"{resolved_generator_network_mode(cfg)} intentionally has no private route to backends.",
                flush=True,
            )
        else:
            baseline_scenarios = [
                name
                for name in scenario_names
                if bool((catalog[name] or {}).get("direct_baseline", False))
            ]
            if baseline_scenarios:
                print("\nDIRECT BACKEND CONTROL PHASE", flush=True)
                print("  No Octavia load balancers will be created for these runs.", flush=True)
                print("  Scenarios: " + ", ".join(baseline_scenarios), flush=True)
            for scenario_name in baseline_scenarios:
                for rep in range(1, baseline_repetitions + 1):
                    cool_down()
                    execute_run("baseline", scenario_name, "direct", rep)

    if args.direct_baselines_only:
        schedule: list[tuple[str, str, int]] = []
        print(
            "\nDirect-control-only mode complete; skipping Octavia load-balancer runs.",
            flush=True,
        )
    else:
        schedule = [
            (flavor, scenario_name, rep)
            for rep in range(1, repetitions + 1)
            for flavor in flavors
            for scenario_name in scenario_names
        ]
        if campaign.get("randomize_run_order", campaign.get("randomize_flavor_order", True)):
            random.shuffle(schedule)

        try:
            if args.reuse_load_balancer:
                print(
                    "\nPERSISTENT LOAD-BALANCER CAMPAIGN MODE",
                    flush=True,
                )
                print(
                    "  One LB/amphora will be created per flavor and reused across every selected scenario/repetition.",
                    flush=True,
                )
                for flavor in flavors:
                    try:
                        prepare_campaign_lb(
                            config,
                            flavor=flavor,
                            campaign_id=campaign_id,
                            lb_create_attempts=lb_create_attempts,
                            lb_create_retry_delay_seconds=lb_create_retry_delay_seconds,
                        )
                        prepared_campaign_flavors.add(flavor)
                    except subprocess.CalledProcessError as exc:
                        failure = {
                            "failed_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
                            "target_kind": "octavia_campaign_lb",
                            "flavor": flavor,
                            "scenario": None,
                            "repetition": None,
                            "returncode": exc.returncode,
                            "command": [str(x) for x in (exc.cmd if isinstance(exc.cmd, (list, tuple)) else [exc.cmd])],
                        }
                        failures.append(failure)
                        if not args.continue_on_error:
                            raise
                        print(
                            f"WARNING: persistent LB for flavor {flavor} could not be created; "
                            "all Octavia runs for that flavor will be skipped.",
                            flush=True,
                        )

                if args.pause_after_lb_create and prepared_campaign_flavors:
                    import sys

                    if not sys.stdin.isatty():
                        raise SystemExit(
                            "--pause-after-lb-create requires an interactive terminal"
                        )
                    print(
                        "\nPAUSED AFTER PERSISTENT LB CREATION",
                        flush=True,
                    )
                    print(
                        "Disable the experimental Octavia flavor(s) now if desired. "
                        "The existing LB/amphora does not need the flavor to remain enabled.",
                        flush=True,
                    )
                    input("Press Enter to start the Octavia benchmark scenarios... ")

            for flavor, scenario_name, rep in schedule:
                if args.reuse_load_balancer and flavor not in prepared_campaign_flavors:
                    continue
                cool_down()
                execute_run(flavor, scenario_name, "octavia", rep)
        finally:
            if args.reuse_load_balancer:
                print("\nCleaning up persistent campaign load balancer(s)...", flush=True)
                for flavor in sorted(prepared_campaign_flavors):
                    destroy_campaign_lb(config, flavor=flavor, campaign_id=campaign_id)

    try:
        run(str(PYTHON), "scripts/compare.py", str(ROOT / "results"))
    except subprocess.CalledProcessError:
        if not args.continue_on_error:
            raise
        print("WARNING: comparison generation failed; preserving campaign results.", flush=True)

    if failures:
        failure_summary = ROOT / "results" / (
            "campaign-failures-"
            + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + ".yml"
        )
        failure_summary.write_text(
            yaml.safe_dump({"failures": failures}, sort_keys=False), encoding="utf-8"
        )
        print(f"\nCampaign failures: {len(failures)}", flush=True)
        print(f"Failure summary: {failure_summary.relative_to(ROOT)}", flush=True)
    print("\nCompleted:")
    for out in outputs:
        print(f"  {out.relative_to(ROOT)}")
    if failures and args.continue_on_error:
        print(
            f"\nWARNING: campaign completed with {len(failures)} failed run(s); "
            "see the failure summary and per-run orchestration diagnostics above.",
            flush=True,
        )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc

