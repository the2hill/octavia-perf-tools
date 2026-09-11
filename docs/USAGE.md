# Usage Guide

## 1. Create a local configuration

```bash
cp config/example.yml config/local.yml
```

At minimum set:

- `openstack.cloud`
- `openstack.admin_cloud`
- `openstack.region_name`
- `network.external_network`
- `ssh.operator_cidr`
- `vm.image`
- `octavia.flavors`

Credentials stay in `clouds.yaml`. `openstack.cloud` is the tenant benchmark profile; `openstack.admin_cloud` is a separate operator profile used only for Amphora/Nova/Neutron inventory and failure diagnostics.

## 2. Bootstrap and validate

```bash
make bootstrap
make validate CONFIG=config/local.yml
```

Validation checks local configuration, OpenStack connectivity/resources, and Barbican when an enabled TLS-termination scenario requires it. It also syntax-checks `playbooks/configure.yml`, which verifies that the repository-local roles can be resolved before provisioning begins.

The expected role layout is:

```text
roles/
  common/
  backend/
  locust/
```

`ansible.cfg` sets `roles_path = ./roles`. Run Ansible commands from the repository root (or explicitly set `ANSIBLE_CONFIG` to the repository's `ansible.cfg`).

## 3. Provision the reusable fleet

```bash
make provision CONFIG=config/local.yml
```

The same generator/backend fleet is reused across Octavia flavor/scenario runs. Reusing it is important for fair comparisons.

### Controller-to-FIP MTU protection

By default provisioning queries the external network MTU and installs a temporary host route for the current master FIP on the machine running Ansible. This is specifically for environments where the controller itself is on a jumbo tenant network but the external network is smaller (for example tenant MTU 3942 and PUBLICNET MTU 1500). The controller needs passwordless `sudo`/Ansible `become` for this route operation.

```yaml
ssh:
  manage_controller_fip_route: true
  controller_fip_mtu: auto
```

`auto` uses the MTU returned by Neutron for `network.external_network`. Set an integer only when the cloud metadata is incorrect. If your controller networking is managed externally, set `manage_controller_fip_route: false`. `make destroy` restores any prior exact `/32` route recorded by the harness.

Provisioning also validates the private management path before fact gathering: the master waits for TCP/22 to each backend and Locust worker, then the generated inventory uses an explicit key-bearing SSH `ProxyCommand`. If this phase fails, test from the master directly with `nc -vz <private-ip> 22`; a TCP failure is a Neutron/security-group/guest-readiness issue, while a successful TCP test followed by an Ansible failure points to SSH/proxy configuration.

## 4. Run the configured default matrix

```bash
make benchmark CONFIG=config/local.yml
```

The default matrix is intentionally request-rate/TLS focused. Connection-capacity and heavier bandwidth/CPS scenarios are opt-in because they substantially increase campaign time and resource pressure.

### Canonical baseline runbook

For the standard single-flavor campaign use:

```bash
./scripts/run_baseline_suite.sh
```

Its lifecycle is intentionally different from a basic standalone `benchmark.py` invocation:

```text
1. validate canonical workload settings
2. optionally rebuild the reusable generator/backend fleet
3. collect selected direct-to-nginx controls once
4. create one persistent Octavia LB/amphora for FLAVOR
5. for each scenario/repetition:
     create scenario listener/pool/members/health monitor
     run the workload
     remove scenario child resources and ephemeral Barbican secrets
     keep the LB/amphora
6. delete the persistent LB after the Octavia phase
7. regenerate comparison artifacts
```

This is preferred for controlled flavor characterization because the Amphora placement and VM remain constant across the suite. Scenario protocol changes do not require a new Amphora: HTTP, TLS passthrough, TLS termination, and re-encryption replace the listener/pool configuration on the same LB.

The direct controls are also collected once per suite, not before every Octavia scenario. They exist to establish generator/backend headroom; the underlying generator/backend fleet is unchanged during the suite.

Useful runbook overrides:

```bash
CONFIG=config/local.yml \
FLAVOR=amphora-default \
REPETITIONS=3 \
LB_CREATE_ATTEMPTS=3 \
LB_CREATE_RETRY_DELAY_SECONDS=30 \
./scripts/run_baseline_suite.sh
```

Reuse an already provisioned generator/backend fleet:

```bash
REBUILD=0 ./scripts/run_baseline_suite.sh
```

For experimental flavors that should be disabled immediately after their first LB is created:

```bash
PAUSE_AFTER_LB_CREATE=1 \
FLAVOR=my-experimental-flavor \
./scripts/run_baseline_suite.sh
```

The runbook pauses only after the persistent LB/amphora is successfully provisioned and prints that the flavor can be disabled. Disable the flavor, then press Enter; subsequent scenarios reuse the existing LB and do not create another Amphora.

## Find maximum sustainable RPS

Plain HTTP:

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_1k_max_rps \
  --repetitions 1
```

TLS terminated by Octavia:

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario tls_termination_1k_max_rps \
  --repetitions 1
```

Compare all major TLS datapaths:

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_1k_max_rps \
  --scenario tls_passthrough_1k_max_rps \
  --scenario tls_termination_1k_max_rps \
  --scenario tls_termination_reencrypt_1k_max_rps \
  --repetitions 1
```

Tune the search in `config/local.yml`:

```yaml
max_rps:
  start_users: 500
  max_users: 64000
  growth_factor: 2.0
  spawn_rate: 4000
  settle_seconds: 10
  measure_seconds: 45
  failure_threshold_percent: 1.0
  p99_max_ms: 1000
  search_resolution_users: 250
  max_search_steps: 16
  user_reach_timeout_seconds: 60
```

A level must satisfy both the failure-rate and p99 gates. If the search reaches `max_users` without a failing level, `summary.json` marks the result as an unbounded lower bound. Increase `max_users` only after confirming generator/backend CPU and network headroom.

## Drive simultaneous connections to the generator-safe maximum

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_max_connections_active \
  --scenario tls_termination_max_connections_active \
  --repetitions 1
```

The max-connection staircase is specified **per generator VM**:

```yaml
connection_capacity:
  max_levels_per_worker: [250, 1250, 2500, 6250, 12500, 18750, 25000, 31250, 37500, 43750, 50000, 52500, 55000]
  source_port_guard_per_worker: 55000
```

With four generator VMs, the higher-resolution staircase runs from 1,000 up through 220,000 global connections, with 25,000-connection steps through much of the upper range and smaller final steps. With twelve VMs the same per-worker profile automatically ends at 660,000. If the final level passes, add generator VMs/source IPs to search higher; do not label the generator guard as the Octavia maximum. For an exploratory ceiling search, start with `--repetitions 1`, then repeat a narrower standard capacity staircase around the discovered transition for publication-quality measurements.

## Run one scenario against all configured flavors

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_connection_capacity_active
```

## Run HTTP and TLS connection-capacity tests

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_connection_capacity_active \
  --scenario tls_termination_connection_capacity_active
```

## Run a complete connection-capacity TLS comparison

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_connection_capacity_active \
  --scenario tls_passthrough_connection_capacity_active \
  --scenario tls_termination_connection_capacity_active \
  --scenario tls_termination_reencrypt_connection_capacity_active
```

## Run idle versus active connection state

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_connection_capacity_idle \
  --scenario http_connection_capacity_active \
  --scenario tls_termination_connection_capacity_idle \
  --scenario tls_termination_connection_capacity_active
```

## Tune listener policy above the workload

The example configuration deliberately keeps listener policy above the test:

```yaml
octavia:
  listener:
    # Used by normal RPS/CPS/bandwidth scenarios.
    connection_limit: 100000
    # Used only by connection_capacity scenarios.
    capacity_connection_limit: 1000000
    timeout_client_data_ms: 300000
    timeout_member_data_ms: 300000
```

Keep `connection_limit` above the largest concurrency used by normal Locust/max-RPS scenarios. Do not set `capacity_connection_limit` below the largest connection-capacity level. Keep `timeout_client_data_ms` above the idle hold duration or the idle test will measure the listener timeout rather than a capacity ceiling. `make validate` checks these conditions.

## Tune connection-capacity levels

Example for smaller Octavia flavors:

```yaml
connection_capacity:
  processes_per_vm: 2
  levels: [1000, 2500, 5000, 10000, 20000, 40000]
  ramp_seconds: 30
  hold_seconds: 60
  heartbeat_seconds: 10
  failure_threshold_percent: 1.0
  source_port_guard_per_worker: 55000
```

Example for a larger campaign with more source IPs:

```yaml
vm:
  locust:
    worker_vms: 12
    processes_per_vm: 4
    flavor: auto
    min_vcpus: 4
    min_ram_mb: 8192

connection_capacity:
  processes_per_vm: 2
  levels: [10000, 50000, 100000, 200000, 400000, 600000]
  ramp_seconds: 60
  hold_seconds: 120
  heartbeat_seconds: 15
  source_port_guard_per_worker: 55000
```

With 12 generator VMs, a 600,000 global target is 50,000 sockets per source IP, below the default 55,000 guard.

## Run only one Octavia flavor

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --flavor my-octavia-flavor \
  --scenario tls_termination_connection_capacity_active \
  --repetitions 3
```

## Tenant-VIP test

Recommended when isolating Octavia itself:

```yaml
benchmark:
  traffic_path: tenant_vip

generator_network:
  mode: auto
```

`auto` resolves to `shared`.

## Floating-IP / external-path test

Recommended for testing the extra FIP/external path:

```yaml
benchmark:
  traffic_path: floating_ip

generator_network:
  mode: auto
```

`auto` resolves to `dedicated_external`, so the workers have their own subnet/router and cannot accidentally reach the LB over the backend tenant network.

## Separate generator network while still testing the tenant VIP

```yaml
benchmark:
  traffic_path: tenant_vip

generator_network:
  mode: dedicated_routed
```

This adds a routed generator subnet while preserving the tenant VIP as the target. Use it only when that extra L3 hop is intentionally part of the experiment.

## Example: broad flavor characterization campaign

For each flavor, prefer persistent-LB mode so all scenarios/repetitions use the same Amphora:

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --flavor my-octavia-flavor \
  --reuse-load-balancer \
  --scenario http_1k_keepalive \
  --scenario tls_termination_1k_keepalive \
  --scenario http_1k_connection_churn \
  --scenario tls_termination_1k_connection_churn \
  --scenario http_connection_capacity_active \
  --scenario tls_termination_connection_capacity_active \
  --scenario http_1m_keepalive
```

Without `--reuse-load-balancer`, standalone `benchmark.py` retains the original per-run LB create/destroy lifecycle.

Then repeat the same scenario list with `benchmark.traffic_path: floating_ip` if external/FIP behavior is part of the product characterization.

## Understanding capacity results

A capacity run writes:

```text
connection-capacity-summary.csv
raw/<worker>/connection-capacity-pNN.csv
raw/<worker>/connection-latencies-pNN.csv
raw/<worker>/connection-errors-pNN.csv
charts/connection-capacity.png
charts/connection-success.png
charts/connection-establishment-latency.png
charts/connection-establishment-rate.png
REPORT.md
RUN_MANIFEST.md
summary.json
```

Important fields in `summary.json`:

- `max_sustainable_connections`
- `max_tested_connections`
- `peak_established_connections`
- `capacity_limit_reached`
- `peak_connection_establishment_rate_cps`
- `capacity_failure_threshold_percent`

For a standard capacity scenario, if `capacity_limit_reached` is false, increase `connection_capacity.levels`; the test demonstrated a lower bound but did not find the ceiling. For a `*_max_connections_active` scenario, a false value at the final generated level means the **generator source-port safety ceiling** was reached. Increase `vm.locust.worker_vms` (or deliberately provide additional source IPs) rather than raising the per-worker guard blindly.

For `*_max_rps` runs, also inspect:

- `max_sustainable_rps`
- `max_sustainable_rps_users`
- `max_rps_limit_reached`
- `max_rps_generator_limited`
- `max_rps_max_tested_users`
- `max_rps_best_p99_ms`
- `max_rps_best_failure_percent`
- `raw/master/max-rps-stages.csv`
- `charts/max-rps-search.png`

`max_rps_limit_reached: true` means the adaptive search found at least one failing **quality** level and bounded the search. `max_rps_generator_limited: true` means the client fleet could not reach a requested user target in time, so increase generator capacity before treating the result as an Octavia ceiling. If both are false, the configured `max_rps.max_users` passed and the reported RPS is a lower bound.

## Historical comparisons

After a campaign:

```bash
make report
```

Top-level artifacts include:

- `results/comparison.csv` — every run
- `results/comparison-summary.csv` — grouped medians
- `results/comparison-compatibility.txt` — configuration-drift warnings
- `results/comparison-rps-*.png`
- `results/comparison-max-rps-*.png`
- `results/comparison-p99-*.png`
- `results/comparison-throughput-*.png`
- `results/comparison-connections-*.png`
- `results/comparison-connection-establishment-rate-*.png`

Always compare within the same scenario, traffic path, and generator topology. The run fingerprint and manifest exist specifically to catch accidental changes to the benchmark environment.

## Teardown

```bash
make destroy CONFIG=config/local.yml
```

A successful persistent-LB campaign removes its campaign LB automatically after the Octavia phase. `make destroy` is still the full cleanup path for interrupted campaigns or when tearing down the reusable fleet; it removes outstanding benchmark LBs/secrets, compute resources, and harness-created networks/routers.

## Persistent-LB lifecycle, resilience, and failed provisioning

The canonical baseline runbook uses `benchmark.py --reuse-load-balancer`. The selected Octavia flavor is used once to create a persistent campaign LB/amphora; later scenarios reuse that same LB and only create/delete their child resources.

Defaults for the initial persistent LB create are:

```text
LB_CREATE_ATTEMPTS=3
LB_CREATE_RETRY_DELAY_SECONDS=30
```

Override them without editing the repository:

```bash
LB_CREATE_ATTEMPTS=4 \
LB_CREATE_RETRY_DELAY_SECONDS=45 \
./scripts/run_baseline_suite.sh
```

If initial persistent LB provisioning fails, the harness performs this sequence before retrying:

```text
create_campaign_lb.yml fails
    |
    +-- preserve exact Ansible output
    |
    +-- query the failed LB before deletion
    |     - load-balancer object and provisioning/operating status
    |     - Octavia status tree
    |     - amphora IDs/status/image/flavor/management IP where permitted
    |     - Nova server state/fault and console tail for amphora compute IDs
    |     - relevant Neutron VIP/HA/VRRP ports
    |
    +-- destroy the failed LB
    |
    +-- verify the deterministic LB name is absent
    |
    +-- delay, then recreate it
```

A successful retry becomes the one persistent LB used for the rest of the campaign. Initial failed provisioning attempts are diagnostic artifacts, not benchmark samples.

Once the persistent LB exists, a scenario failure does **not** cause the Amphora to be rebuilt. The per-run cleanup calls `destroy_campaign_lb_scenario.yml`, which removes the scenario health monitor, members, pool, listener, temporary FIP route state, and ephemeral Barbican secrets while leaving the persistent LB/amphora intact. With `--continue-on-error`, later scenarios/repetitions can continue on that same Amphora.

The persistent campaign LB itself is deleted in final cleanup after all selected Octavia runs. This also happens when a later scenario raises an exception because the campaign lifecycle uses a `finally` cleanup.

### Experimental flavor pause

Use:

```bash
PAUSE_AFTER_LB_CREATE=1 \
FLAVOR=my-experimental-flavor \
./scripts/run_baseline_suite.sh
```

The pause occurs after the persistent LB/amphora has been created but before any Octavia scenario traffic starts. The flavor may then be disabled; continuing the suite does not need to create another LB/amphora.

For manual campaigns the equivalent flags are:

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --flavor my-experimental-flavor \
  --reuse-load-balancer \
  --pause-after-lb-create \
  --continue-on-error \
  --lb-create-attempts 3 \
  --lb-create-retry-delay-seconds 30 \
  --scenario http_1k_keepalive \
  --scenario tls_termination_1k_keepalive
```

`--pause-after-lb-create` requires an interactive terminal and requires `--reuse-load-balancer`.

### Direct controls once per suite

The baseline runbook first invokes `benchmark.py --direct-baselines-only` with all selected direct-control scenarios, then invokes the Octavia phase with `--skip-baseline`. This prevents the same nginx-direct control from being repeated simply because each Octavia scenario is a separate workload shape.

A manual standalone `benchmark.py` invocation remains backward-compatible: unless `--reuse-load-balancer` is supplied, it creates/destroys an LB per Octavia run; unless `--skip-baseline` or `--direct-baselines-only` is supplied, it performs its normal direct-baseline behavior.

Per-attempt provisioning diagnostics are stored under the persistent campaign-LB result directory, for example:

```text
results/<campaign-id>-<flavor>-campaign-lb/orchestration/lb-create-attempt-01.log
results/<campaign-id>-<flavor>-campaign-lb/orchestration/lb-create-attempt-01-diagnostics.json
results/<campaign-id>-<flavor>-campaign-lb/orchestration/lb-create-attempt-01-cleanup.log
results/<campaign-id>-<flavor>-campaign-lb/orchestration/lb-create-attempt-01-post-cleanup.json
```

Run/scenario failures are summarized under:

```text
results/campaign-failures-<UTC timestamp>.yml
```

The Octavia API can show that provisioning entered `ERROR`, the status tree, and amphora state, but it does not always expose the controller-worker exception that caused the failure. When the diagnostic JSON does not identify the root cause, use the captured load-balancer ID, amphora IDs, compute IDs, and timestamps to search Octavia worker/health-manager logs.

## Combined cross-flavor campaign report

When baseline suites are run **one Octavia flavor at a time**, leave their completed run directories under the same `results/` tree. After all flavors have been tested, build one combined comparison package with:

```bash
make campaign-report
```

or directly:

```bash
.venv/bin/python scripts/compare_campaigns.py results
```

The report scans completed `results/*/summary.json` files. By default it uses the **latest three successful runs per flavor + scenario + traffic path + generator topology**, matching the canonical three-repetition baseline while avoiding accidental mixing with older historical runs.

For an explicit four-flavor comparison:

```bash
.venv/bin/python scripts/compare_campaigns.py results \
  --flavor flavor-a \
  --flavor flavor-b \
  --flavor flavor-c \
  --flavor flavor-d \
  --reference-flavor flavor-a
```

Use every matching historical run instead of the latest three with:

```bash
.venv/bin/python scripts/compare_campaigns.py results --latest-per-group 0
```

The generated package is written to `results/campaign-comparison/` and contains:

```text
README.md                       # simple executive scorecard + overview charts
DETAILED_COMPARISON.md          # actual values and per-scenario compare/contrast tables
selected-runs.csv               # exact source result directories used
scenario-summary.csv            # median/min/max/std/CV/p99/failures/deltas
flavor-scorecard.csv            # compact cross-scenario flavor ranking
scenario-winners.csv            # winner/margin for each comparable scenario population
direct-reference-summary.csv    # recent nginx-direct controls when available
charts/
  composite-dashboard.png              # all-in-one presentation/share view
  flavor-overall-performance-index.png
  scenario-performance-index.png
  scenario-latency-index.png
  scenario-wins.png
  flavor-variability.png
  actual-<scenario>-*.png
  p99-<scenario>-*.png
```

For a quick compare/contrast, open `charts/composite-dashboard.png` first. It combines six views in one image: overall cross-scenario performance index, scenario wins, normalized performance by scenario, normalized p99 latency by scenario, run-to-run coefficient of variation, and median Octavia throughput as a percentage of the matching flavor-scoped direct-nginx control. If a flavor has no scoped direct control, the direct-efficiency panel leaves it out rather than borrowing an unrelated or legacy baseline.

The primary metric is selected from each scenario's semantics rather than pretending every test is the same kind of RPS measurement:

- ordinary 1 KiB keepalive: peak request rate;
- adaptive `*_max_rps`: max sustainable RPS;
- `*_connection_churn`: approximate new connections/s;
- connection-capacity engine: max sustainable simultaneous connections;
- large-payload bandwidth scenarios: estimated application payload Gb/s.

The overview `performance index` normalizes each scenario so its best flavor is 100, then summarizes those indexes across scenarios. This gives a simple high-level comparison without mixing incompatible units. Use `DETAILED_COMPARISON.md` for the actual values behind the index.

Direct nginx runs are retained only as reference measurements and are not ranked as Octavia flavors. The report also checks comparison fingerprints **across flavors** inside each scenario/path/topology population. Use `--strict-fingerprint` to make any detected configuration drift fail the report command.

## Flavor selection and suite provenance

`scripts/run_baseline_suite.sh` is intentionally a **one-Octavia-flavor-at-a-time** runbook. Select the flavor explicitly:

```bash
FLAVOR=my-octavia-flavor REPETITIONS=3 ./scripts/run_baseline_suite.sh
```

If `FLAVOR` is omitted, the runbook reads `octavia.flavors` from the selected config. Exactly one configured flavor is accepted in that mode. If the config contains multiple flavors, the runbook exits and requires `FLAVOR=<name>` rather than silently choosing one.

Every runbook invocation creates a unique `suite_id`. The same suite ID is passed to the direct-control phase and the Octavia phase. Direct nginx results remain `target_kind: direct`, but now also record:

```yaml
suite_id: <suite-id>
baseline_for_flavor: <requested-octavia-flavor>
```

`baseline_for_flavor` is **provenance**, not a claim that the direct path uses that Octavia flavor. It identifies which one-flavor baseline suite collected the control result.

Before persistent-LB creation, `benchmark.py` resolves the requested Octavia flavor to its UUID with openstacksdk. The create playbook passes that UUID to Octavia and asserts that the resulting load balancer reports the same immutable `flavor_id`. A mismatch aborts the suite rather than benchmarking the wrong Amphora. The selected flavor must be enabled for this initial create; it may be disabled after the optional `PAUSE_AFTER_LB_CREATE=1` pause.

For combined reports, new direct controls are associated with their matching `baseline_for_flavor`. Direct controls created before this provenance change appear as `legacy_unscoped`; they are retained for context but are not silently assigned to a flavor-specific Octavia-to-direct ratio.

## Amphora identity and historical Prometheus correlation

Persistent-LB creation captures Amphora and Nova identity before benchmark traffic starts. The capture uses `openstack.admin_cloud` because the Octavia Amphora inventory API is admin-only; normal LB provisioning and test operations continue to use the tenant `openstack.cloud`. During a live campaign use:

```bash
cat state/current_campaign_lbs.yml
```

The registry supports one or several simultaneously prepared flavors. Each entry includes `load_balancer_id`, `octavia_flavor`, the full `amphorae` list, `primary_amphora`, and `prometheus_libvirt_domains`. For a single/standalone Amphora the convenience fields propagated to each run include:

```yaml
amphora_id: <octavia-amphora-uuid>
amphora_role: STANDALONE
amphora_compute_id: <nova-server-uuid>
amphora_instance_name: instance-00123456
amphora_compute_host: <nova-compute-host>
amphora_hypervisor_hostname: <hypervisor-hostname>
prometheus_libvirt_domains:
  - instance-00123456
prometheus_libvirt_domain_regex: instance-00123456
```

For ACTIVE_STANDBY, use the full `amphorae` list; it records both MASTER and BACKUP rather than assuming one VM.

Each run preserves the same data in its collected `target.yml`, generated manifest, and `summary.json`. In addition, the persistent-LB setup directory preserves:

```text
results/<campaign-id>-<flavor>-campaign-lb/campaign-state.yml
```

That file survives final campaign cleanup, so after the Amphora has been deleted you can still recover the exact libvirt domain and historical time window:

```bash
jq '{
  flavor: .octavia_flavor,
  domain: .amphora_instance_name,
  compute_id: .amphora_compute_id,
  compute_host: .amphora_compute_host,
  started: .load_test_started_at_utc,
  completed: .load_test_completed_at_utc
}' results/<run>/summary.json
```

Then use `amphora_instance_name` as the Prometheus `domain` label and set Grafana/Prometheus to the saved absolute UTC load window (optionally padded by about five minutes on each side).

