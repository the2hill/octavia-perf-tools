# Usage Guide

## 1. Create a local configuration

```bash
cp config/example.yml config/local.yml
```

At minimum set:

- `openstack.cloud`
- `openstack.region_name`
- `network.external_network`
- `ssh.operator_cidr`
- `vm.image`
- `octavia.flavors`

Credentials stay in `clouds.yaml` or normal OpenStack environment variables.

## 2. Bootstrap and validate

```bash
make bootstrap
make validate CONFIG=config/local.yml
```

Validation checks local configuration, OpenStack connectivity/resources, and Barbican when an enabled TLS-termination scenario requires it.

## 3. Provision the reusable fleet

```bash
make provision CONFIG=config/local.yml
```

The same generator/backend fleet is reused across Octavia flavor/scenario runs. Reusing it is important for fair comparisons.

## 4. Run the configured default matrix

```bash
make benchmark CONFIG=config/local.yml
```

The default matrix is intentionally request-rate/TLS focused. Connection-capacity and heavier bandwidth/CPS scenarios are opt-in because they substantially increase campaign time and resource pressure.

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
    connection_limit: 1000000
    timeout_client_data_ms: 300000
    timeout_member_data_ms: 300000
```

Do not set `connection_limit` below the largest connection-capacity level. Keep `timeout_client_data_ms` above the idle hold duration or the idle test will measure the listener timeout rather than a capacity ceiling. `make validate` checks both conditions.

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

For each flavor, run:

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_1k_keepalive \
  --scenario tls_termination_1k_keepalive \
  --scenario http_1k_connection_churn \
  --scenario tls_termination_1k_connection_churn \
  --scenario http_connection_capacity_active \
  --scenario tls_termination_connection_capacity_active \
  --scenario http_1m_keepalive
```

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

The harness removes scenario LBs and transient Barbican secrets, compute resources, and harness-created networks/routers.
