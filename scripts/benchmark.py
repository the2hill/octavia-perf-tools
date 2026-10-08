                                        "repetition": rep,
                                        "returncode": exc.returncode,
                                        "command": [
                                            str(x)
                                            for x in (
                                                exc.cmd
                                                if isinstance(exc.cmd, (list, tuple))
                                                else [exc.cmd]
                                            )
                                        ],
                                    }
                                    failures.append(failure)
                                    print(
                                        "\nFAILED RUN: "
                                        f"target=octavia flavor={flavor} "
                                        f"scenario={scenario_name} r{rep:02d} "
                                        f"rc={exc.returncode}",
                                        flush=True,
                                    )
                                    if not args.continue_on_error:
                                        raise
                                    print(
                                        "Keeping the configured scenario and continuing "
                                        "with the remaining repetitions.",
                                        flush=True,
                                    )
                    finally:
                        # Always attempt one scenario cleanup, even when configuration only
                        # partially completed. The playbook is intentionally idempotent and
                        # uses failed_when=false for absent child resources.
                        print(
                            "CLEAN UP SCENARIO ONCE: "
                            f"flavor={flavor} scenario={scenario_name}",
                            flush=True,
                        )
                        try:
                            ansible(
                                "playbooks/destroy_campaign_lb_scenario.yml",
                                config,
                                **setup_common,
                            )
                        except subprocess.CalledProcessError as cleanup_exc:
                            print(
                                "WARNING: final scenario cleanup failed "
                                f"for flavor={flavor} scenario={scenario_name} "
                                f"(rc={cleanup_exc.returncode}).",
                                flush=True,
                            )
            else:
                schedule = [
                    (flavor, scenario_name, rep)
                    for rep in range(1, repetitions + 1)
                    for flavor in flavors
                    for scenario_name in scenario_names
                ]
                if campaign.get(
                    "randomize_run_order",
                    campaign.get("randomize_flavor_order", True),
                ):
                    random.shuffle(schedule)

                for flavor, scenario_name, rep in schedule:
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
