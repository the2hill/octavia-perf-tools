# Octavia Performance Harness

A repeatable Ansible + distributed load-generation benchmark harness for comparing OpenStack Octavia load-balancer flavors while controlling for client, backend, TLS, connection-state, and network-path bottlenecks.

## Design goals

- Provision the benchmark topology in a configurable OpenStack cloud using `clouds.yaml` / `OS_CLOUD`; no credentials are stored in this repository.
- Use one public jump/master VM, with configurable Locust generator placement: shared with the backend tenant network, on a separately routed generator subnet, or isolated behind its own external router for floating-IP tests.
- Run Locust distributed across multiple VMs and multiple worker processes per VM.
- Serve backend traffic with **native nginx on the member VMs** (no backend container layer), with access logging disabled and conservative kernel/socket tuning.
- Benchmark the Octavia VIP on the tenant network by default so public NAT/edge capacity is not accidentally measured as Octavia capacity. In `auto` mode, floating-IP tests move Locust workers onto a dedicated externally routed generator network so the FIP path is exercised from outside the backend tenant network.
- Exercise HTTP, TLS passthrough, TLS termination, backend TLS re-encryption, connection churn, **simultaneous connection-capacity**, adaptive **max sustainable RPS**, generator-safe **max connections**, and payload/bandwidth profiles from a common scenario catalog.
- Generate disposable benchmark certificates locally and use Barbican only for the Octavia TLS secrets needed by a scenario; delete those secrets after the load balancer is removed.
- Run direct-to-backend baselines for the scenarios where they are meaningful to expose backend/client ceilings.
- Collect Locust CSV history for request-rate/CPS-style runs, purpose-built distributed socket-capacity CSVs for simultaneous-connection runs, plus 1-second CPU/memory/network metrics from the master, workers, and backend VMs.
- Snapshot and print a historical run manifest with resolved generator/backend flavors, image identity, node OS/kernel/hardware, nginx/Locust/OpenSSL versions, traffic path, workload shape, TLS datapath, and Octavia metadata.
- Produce per-run charts and scenario-specific cross-flavor comparison artifacts, with fingerprints that warn when test-critical inputs drift between otherwise comparable runs.
- Reuse the same backend and generator fleet for each flavor and scenario so comparisons are controlled.

## Default topology

| Component | Default | Rationale |
|---|---:|---|
| Locust master | 1 VM, >=2 vCPU / 4 GiB | Coordination only; master does not generate user traffic. |
| Locust workers | 4 VMs, >=4 vCPU / 8 GiB each | 16 worker processes by default; enough client-side headroom for many LB flavors. |
| Backend members | 4 VMs, >=4 vCPU / 8 GiB each | Native nginx with static page-cache responses; intentionally overprovisioned. |
| Backend endpoints | HTTP :80 + HTTPS :443 | Supports control, passthrough, and re-encryption from the same fleet. |
| Payloads | 1 KiB, 64 KiB, 1 MiB | 1 KiB for RPS/latency; larger payloads for bandwidth profiles. |
| Pool algorithm | ROUND_ROBIN | Predictable distribution during comparative tests. |
| Health monitor | HTTP/HTTPS GET `/healthz` | Protocol follows the selected scenario. |
| Generator network mode | `auto` | Shared network for tenant-VIP tests; dedicated external generator network for FIP tests. |

The `auto` compute flavor selector chooses the smallest visible Nova flavor meeting each configured vCPU/RAM floor. For a long-lived benchmark program, pin exact Nova flavor names after the first successful run so infrastructure stays identical over time.

## Default scenario matrix

Four core scenarios run by default:

| Scenario | Frontend | Backend | Purpose |
|---|---|---|---|
| `http_1k_keepalive` | HTTP | HTTP | Request-rate/latency control case. |
| `tls_passthrough_1k_keepalive` | HTTPS passthrough | nginx TLS | Measures end-to-end TLS without Octavia terminating it. |
| `tls_termination_1k_keepalive` | `TERMINATED_HTTPS` + Barbican PKCS#12 | HTTP | Measures Octavia frontend TLS termination cost. |
| `tls_termination_reencrypt_1k_keepalive` | `TERMINATED_HTTPS` + Barbican PKCS#12 | TLS enabled pool + Barbican CA validation | Measures frontend termination plus Octavia-to-member re-encryption. |

The example configuration also ships disabled-but-ready profiles for:

- `http_1k_connection_churn` — one request per TCP connection, useful as an approximate CPS profile.
- `tls_termination_1k_connection_churn` — one request per connection through TLS termination, stressing connection/TLS setup.
- `http_connection_capacity_idle` / `http_connection_capacity_active` — simultaneous HTTP connection ceilings.
- `tls_passthrough_connection_capacity_active` — simultaneous active TLS passthrough connections.
- `tls_termination_connection_capacity_idle` / `tls_termination_connection_capacity_active` — simultaneous TLS sessions terminated by Octavia.
- `tls_termination_reencrypt_connection_capacity_active` — simultaneous active frontend TLS sessions with backend TLS re-encryption.
- `http_1k_max_rps`, `tls_passthrough_1k_max_rps`, `tls_termination_1k_max_rps`, and `tls_termination_reencrypt_1k_max_rps` — adaptive searches for the highest sustainable request rate while enforcing failure-rate and p99 latency gates.
- `http_max_connections_active`, `tls_passthrough_max_connections_active`, `tls_termination_max_connections_active`, and `tls_termination_reencrypt_max_connections_active` — push simultaneous active connections through a per-generator staircase ending at the configured source-port safety limit.
- `http_64k_keepalive` and `http_1m_keepalive` — response-bandwidth profiles.
- `tls_termination_64k_keepalive` — TLS-termination bandwidth profile.

Connection-capacity scenarios use a distributed asyncio socket holder on the Locust worker VMs rather than Locust itself. They report establishment/survival percentages and a maximum sustainable simultaneous-connection level. The configured targets are global across all generator VMs/processes.

The `*_max_rps` scenarios are different from the normal fixed Locust staircase. They start at `max_rps.start_users`, double concurrency until a level violates the configured request-failure or p99-latency threshold, then bisect the last passing/failing user range. Reports distinguish a bounded ceiling from a lower-bound result when `max_rps.max_users` is reached without a failure.

The `*_max_connections_active` scenarios scale their global connection targets from `connection_capacity.max_levels_per_worker × vm.locust.worker_vms`. The default last per-worker target is 55,000, matching the source-port guard. If every level passes, the report says the generator-safe ceiling was reached and tells you to add generator VMs/source IPs before claiming an Octavia maximum.

The harness also raises and records the benchmark listener `connection_limit` and client/member inactivity timeouts so an API policy cap or idle timeout is not mistaken for the flavor's resource ceiling. Normal request-rate, churn, and bandwidth tests use `octavia.listener.connection_limit` (100,000 by default); simultaneous connection-capacity tests use the separate `octavia.listener.capacity_connection_limit` (1,000,000 by default) so an oversized HAProxy `maxconn` is not carried into every RPS test.

Enable opt-in profiles by adding their names to `scenarios.enabled`, or select a subset for one campaign with repeated `--scenario` arguments. See [`docs/SCENARIOS.md`](docs/SCENARIOS.md) for the measurement semantics and [`docs/USAGE.md`](docs/USAGE.md) for campaign examples.

## Max-ceiling quick examples

Find the maximum sustainable HTTP RPS for every configured Octavia flavor:

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_1k_max_rps \
  --repetitions 1
```

Find the maximum sustainable TLS-termination RPS:

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario tls_termination_1k_max_rps \
  --repetitions 1
```

Drive active HTTP and terminated-TLS simultaneous connections to the generator-safe ceiling:

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_max_connections_active \
  --scenario tls_termination_max_connections_active \
  --repetitions 1
```

See [`docs/SCENARIOS.md`](docs/SCENARIOS.md) for the pass/fail semantics and [`docs/USAGE.md`](docs/USAGE.md) for tuning `max_rps` and generator capacity.

## Traffic path and generator network topology

Traffic path and generator placement are separate controls. The recommended default is:

```yaml
benchmark:
  traffic_path: tenant_vip

generator_network:
  mode: auto
```

`auto` resolves the topology based on the traffic path:

| `benchmark.traffic_path` | `generator_network.mode: auto` resolves to | Result |
|---|---|---|
| `tenant_vip` | `shared` | Workers live on the backend/LB tenant network and hit the VIP directly. This is the cleanest Octavia datapath measurement. |
| `floating_ip` | `dedicated_external` | Workers live on their own subnet/router and reach the LB through its FIP. There is intentionally no private route from workers to backends. |

You can override `auto` with any of these modes:

- `shared` — Locust workers use `network.name`, the same tenant network as the backends and Octavia VIP. Use this for the lowest-path-overhead VIP benchmark, or when you intentionally want an FIP test originating from the same tenant network.
- `dedicated_routed` — Locust workers use `generator_network.name`, a separate subnet routed to the backend/VIP network. This keeps generator L2 traffic separate while deliberately adding an L3 router hop to tenant-VIP testing. If the harness creates this topology, it attaches both benchmark subnets to the harness-owned benchmark router. If `generator_network.create: false`, the pre-existing generator subnet must already have the necessary route.
- `dedicated_external` — Locust workers use a separate generator subnet with its own router to `network.external_network`; no tenant route to backend private addresses is created. This mode requires `benchmark.traffic_path: floating_ip`.

Example isolated FIP configuration:

```yaml
benchmark:
  traffic_path: floating_ip

generator_network:
  mode: dedicated_external
  create: true
  name: octavia-perf-generator-net
  subnet_name: octavia-perf-generator-subnet
  router_name: octavia-perf-generator-router
  cidr: 10.78.0.0/24
```

The Locust master is dual-homed in the dedicated modes: its workload NIC remains on the backend network for SSH/jump-host management, while its generator NIC communicates directly with Locust workers. The workers themselves have only the generator-network NIC, so benchmark requests cannot accidentally originate on the management/backend network. The harness removes the generator-side default route from the dual-homed master so its public SSH/FIP return path remains pinned to the workload/control NIC.

### FIP MTU handling

The harness preserves the cloud-native tenant-network MTU for benchmark traffic, but it does not assume that a jumbo tenant MTU can traverse the external/FIP network unchanged. During provisioning it queries `network.external_network` for its MTU and, by default, installs a temporary `/32` route on the Ansible controller for the newly allocated master FIP using that external MTU. SSH-dependent playbooks (`configure`, benchmark execution, and result collection) reconcile that route again before contacting the master, so a controller reboot, DHCP renewal, or network-service restart cannot silently remove the workaround. The prior route is restored by `make destroy`. This avoids SSH/Ansible stalls when the controller lives on a jumbo tenant network but PUBLICNET is 1500 bytes. Disable this with `ssh.manage_controller_fip_route: false` if the controller route is managed outside the harness; `ssh.controller_fip_mtu` can override the discovered MTU.

For `benchmark.traffic_path: floating_ip`, the same external-network MTU is applied as a temporary per-target route on the Locust master/workers before each FIP benchmark and restored afterward. This keeps FIP tests on the real public-path MTU while leaving tenant-VIP benchmarks at the tenant network's native MTU.

Private-node SSH is validated in two stages: the master must first establish TCP/22 to every backend/worker address, then Ansible performs the SSH handshake through an explicit `ProxyCommand` that supplies the generated benchmark key to the jump-host hop. This makes routing/security-group failures distinct from SSH key/proxy failures.

A direct-to-nginx baseline is possible in `shared` and `dedicated_routed`. It is automatically skipped in `dedicated_external`, because lack of a private generator-to-backend route is an intentional part of that topology. The resolved generator mode, network/subnet/CIDR, isolation state, and master workload/generator IPs are captured in every run manifest and included in the comparison fingerprint.

## TLS and Barbican behavior

`make provision` generates an ephemeral benchmark CA plus frontend/backend certificates under `state/tls/` after the backend IPs are known. The backend certificate contains every backend private IP in its SAN list and is installed directly into nginx.

For TLS termination scenarios, the frontend certificate/key/CA chain is exported as an unencrypted PKCS#12 benchmark bundle and uploaded as a short-lived Barbican secret. For re-encryption scenarios, the benchmark CA certificate is also uploaded to Barbican and configured on the TLS-enabled Octavia pool for member-certificate validation. Per-run secret references are written immediately to `state/current_secrets.yml` so cleanup can recover from a partially failed LB build. The LB is deleted first, then its ephemeral Barbican secrets are deleted.

The generated certificates are **benchmark-only**, not production identity material. Locust defaults to certificate verification disabled for these generated certificates (`tls.client_insecure: true`) because the frontend is addressed by VIP/FIP rather than the synthetic certificate DNS name. You can change that behavior when using a real trusted certificate/DNS setup.

Optional listener/pool TLS versions and ciphers can be configured under `tls:`. Empty values leave provider/cloud defaults in place.

## Prerequisites

- Python 3.10+
- `ssh-keygen`
- `openssl`
- An OpenStack `clouds.yaml` profile with Nova, Neutron, Octavia, and (for TLS termination/re-encryption) Barbican/key-manager permissions
- A routable external network for the Locust master floating IP and SNAT
- An Ubuntu-like image with cloud-init and Python; Ubuntu 24.04 is the recommended baseline
- Enough quotas for 1 master + configured workers + configured backends, ports, security groups, floating IPs, load balancers, temporary Barbican secrets, and (for dedicated generator modes) an additional network/subnet/router

`make validate` probes the key-manager endpoint whenever an enabled scenario requires Barbican.

## OpenStack authentication

Prefer `~/.config/openstack/clouds.yaml` and reference only the profile name in `config/local.yml`. You can also use normal `OS_*` environment variables supported by openstacksdk/Ansible. Do not put usernames, passwords, application credentials, or tokens in this repository.

For SJC3, start with your existing working cloud profile rather than embedding credentials here. Endpoint and credential details therefore remain outside the Git repository.

## Quick start

```bash
cp config/example.yml config/local.yml
# edit cloud/environment label, image, external network, operator_cidr, and Octavia flavor names
make bootstrap
make validate CONFIG=config/local.yml
make provision CONFIG=config/local.yml
make benchmark CONFIG=config/local.yml
```

`ansible.cfg` sets `roles_path = ./roles`, so the repository-level `roles/common`, `roles/backend`, and `roles/locust` roles are resolved even though the playbooks live under `playbooks/`. `make validate` also syntax-checks `playbooks/configure.yml` first so a missing or mispackaged role is caught before cloud resources are provisioned.

Run selected scenarios/flavors without editing the file:

```bash
.venv/bin/python scripts/benchmark.py \
  --config config/local.yml \
  --scenario http_1k_keepalive \
  --scenario tls_termination_1k_keepalive \
  --flavor my-small-octavia-flavor \
  --flavor my-large-octavia-flavor
```

If backend addresses change, regenerate and reinstall backend certificates with:

```bash
make configure CONFIG=config/local.yml
```

## Canonical baseline-suite workflow

For a controlled single-flavor characterization campaign, prefer:

```bash
./scripts/run_baseline_suite.sh
```

The baseline runbook deliberately separates infrastructure controls from Octavia testing:

```text
reusable generator/backend fleet
    |
    +-- direct-to-nginx controls, once per suite
    |
    +-- create one persistent Octavia LB/amphora for the selected flavor
            |
            +-- scenario 1: create listener/pool/members/HM -> test -> delete children
            +-- scenario 2: create listener/pool/members/HM -> test -> delete children
            +-- ...
            +-- all repetitions use the same LB/amphora
            |
            +-- delete the persistent LB after the Octavia phase
```

The persistent-LB mode avoids rebuilding the Amphora between scenarios or repetitions. This reduces provisioning noise and keeps Nova placement, CPU model, virtual NICs, and the Amphora image constant for the campaign. HTTP, TLS passthrough, and TLS termination still get their own scenario-specific listener/pool configuration; only those child resources are replaced.

For an experimental Octavia flavor that must be disabled after first use, pause immediately after the persistent LB is provisioned:

```bash
PAUSE_AFTER_LB_CREATE=1 ./scripts/run_baseline_suite.sh
```

The script prints the persistent LB ID/VIP and waits for Enter. At that point the LB/amphora already exists, so the flavor can be disabled before benchmark scenarios begin. The baseline runbook creates one persistent LB for `FLAVOR`; manual `benchmark.py --reuse-load-balancer` creates one persistent LB per selected flavor.

Standalone `benchmark.py` remains backward-compatible: unless `--reuse-load-balancer` is supplied, normal Octavia runs create and destroy a load balancer per run.

## Results and historical documentation

Artifacts appear under:

```text
results/<timestamp>-<scenario>-<flavor>-<target>-rNN/
```

Each completed run includes:

- `REPORT.md`
- `RUN_MANIFEST.md` — human-readable historical test specification; also printed after every run
- `manifest.yml` / `manifest.json` — machine-readable run specification
- `timing.yml` — orchestration and actual load-test UTC window/elapsed time
- `tls-material.json` — non-secret certificate hashes/key-size/backend-SAN metadata when TLS material exists
- `node-specs/*.yml` — per-VM OS/kernel/hardware/software snapshots
- `summary.json`
- Locust stats/history/failures CSVs for `locust` scenarios
- `max-rps-stages.csv` and `charts/max-rps-search.png` for adaptive `*_max_rps` scenarios
- distributed `connection-capacity-*.csv`, `connection-latencies-*.csv`, and `connection-errors-*.csv` files for connection-capacity scenarios
- `connection-capacity-summary.csv` for connection-capacity runs
- per-node metrics CSVs
- `charts/rps.png` / `charts/latency.png` for Locust scenarios
- `charts/payload-throughput.png` when payload size is known
- `charts/connection-capacity.png`, `charts/connection-success.png`, `charts/connection-establishment-latency.png`, and `charts/connection-establishment-rate.png` for capacity scenarios
- `charts/cpu.png`
- `charts/network_tx.png`

The top-level `results/comparison.csv` retains every run. `comparison-summary.csv` aggregates by **scenario + traffic path + generator-network mode + Octavia flavor**. RPS, **max sustainable RPS**, p99, payload-throughput, simultaneous-connection-capacity, and capacity-ramp establishment-rate charts are emitted separately for each scenario/path/generator-topology population, so unlike network paths and benchmark engines are never averaged together. `comparison-compatibility.txt` checks fingerprints within each scenario/path/generator-topology/target population and warns about drift.

## Historical run specification

Every completed run writes and prints a specification before the performance report is generated. It includes:

- benchmark ID and actual UTC test window
- scenario name/description, tenant-VIP vs floating-IP path, generator-network configured/resolved mode, generator network/subnet/CIDR and isolation state, request path/payload bytes, keepalive vs connection-close behavior
- frontend TLS termination, backend TLS, re-encryption, listener/pool/member protocols and ports
- whether frontend/CA Barbican secrets were used, plus configured TLS versions/ciphers (but not secret payloads)
- cloud/region/environment label, Git commit/dirty state, and a benchmark-implementation hash
- requested/resolved VM image identifiers/checksums
- Nova flavor name/ID, vCPU, RAM, disk, Rx/Tx factor, and extra specs for master/workers/backends
- generator VM count, Locust processes per VM, total worker-process count, and backend member count
- per-node distro, kernel, CPU model, RAM, private interface, MTU, Python/nginx/Locust/OpenSSL versions
- OpenStack placement metadata when exposed by Nova
- Octavia provider/flavor ID, LB/VIP/listener/pool IDs, target address, health-monitor configuration
- exact fixed Locust concurrency staircase or adaptive max-RPS search settings, plus exact connection-capacity targets/ramp/hold/heartbeat/process/socket-limit settings for connection-capacity scenarios
- optional campaign/cloud-build/operator notes

The comparison fingerprint intentionally excludes the Octavia flavor under test and ephemeral LB/secret IDs. Compatibility is assessed within a scenario/traffic-path/generator-topology population; changing the test scenario or generator placement is expected to change the fingerprint.

## Benchmark methodology

The default concurrency staircase is 250, 500, 1k, 2k, 4k, then 8k concurrent Locust users. Each Octavia flavor/scenario combination runs three times by default, with run order randomized to reduce time/order bias. Static responses stay hot in the nginx page cache. Locust uses `FastHttpUser` and no artificial think-time, making this a saturation-oriented benchmark rather than an end-user behavior simulation.

For comparative work:

1. Keep the Nova flavors, image, backend count, worker count, scenario, traffic path, **generator-network mode**, and staircase unchanged.
2. Use direct backend baselines to prove client/backend headroom where the scenario and network topology allow them; the canonical baseline runbook collects each selected direct control once because the reusable generator/backend fleet does not change. `dedicated_external` intentionally cannot run a private direct baseline.
3. Test Octavia flavor/scenario combinations serially, not simultaneously. The canonical baseline runbook reuses one LB/amphora for the selected flavor and replaces only scenario child resources between tests.
4. Keep the default three randomized repetitions (or increase them) and compare medians and variance.
5. Reject or rerun results where generator/backend CPU or network is the bottleneck.
6. Compare HTTP, passthrough, termination, re-encryption, connection churn, and payload sizes as separate populations.
7. Record cloud build/version and Octavia provider when publishing results.

For connection-close profiles, RPS is reported as an **approximation** of new TCP connections per second because each request requests connection closure. Concurrent-connection scenarios are different: a dedicated multi-process asyncio holder opens and retains sockets at configured global levels, then reports establishment and survival rates. `idle` capacity holds sockets without application traffic during the hold interval and verifies them at the end; `active` capacity periodically sends requests on every connection. The harness guards against client ephemeral-port exhaustion per generator VM and captures file-descriptor/source-port settings in the run manifest.

For bandwidth profiles, the report estimates application payload Gb/s from payload size × RPS; host NIC telemetry remains the better view of actual byte rate because it includes protocol overhead.

## Native nginx backend

Backends are deliberately not containerized. Ansible installs nginx directly, disables access logging, raises descriptor/socket limits, generates deterministic static files, and configures both HTTP and HTTPS endpoints. This minimizes extra scheduling/NAT/overlay variables on member VMs and keeps backend capacity easy to reason about.

## Provider capability caveat

Octavia provider drivers do not necessarily expose the same TLS feature set. If a flavor/provider does not support TLS termination or TLS-enabled backend pools, that scenario can fail while its listener/pool resources are configured even though the persistent LB and HTTP control scenario work. Treat that as an explicit provider capability result rather than silently falling back to a different datapath.

## Teardown

```bash
make destroy CONFIG=config/local.yml
```

The canonical baseline runbook deletes its persistent campaign LB in a `finally` cleanup after the Octavia phase. `make destroy` remains the full environment cleanup path: it cleans outstanding benchmark LBs/secrets and removes the compute resources and any harness-created generator/network resources. Keep a unique `run_prefix` when multiple operators share a project.

## Detailed documentation

- [`docs/SCENARIOS.md`](docs/SCENARIOS.md) — what every scenario measures, idle vs active capacity, generator-side false ceilings, and recommended comparison sets.
- [`docs/USAGE.md`](docs/USAGE.md) — setup, validation, copy/paste commands, tenant-VIP/FIP examples, connection-capacity tuning, and larger campaigns.
- [`docs/AMPHORA_PERFORMANCE_TUNING.md`](docs/AMPHORA_PERFORMANCE_TUNING.md) — Octavia/HAProxy logging, generated-config checks, one-vCPU diagnostics, image tuning, CPU pinning, and multiqueue/SR-IOV follow-up tests.

## Useful next extensions

The current harness now covers the major HTTP/TLS request-rate, CPS-like, simultaneous-connection, and bandwidth dimensions. Useful future additions include:

- operator-side Octavia/amphora CPU/network telemetry correlation
- HTTP/2 where the selected Octavia provider supports it
- long-lived WebSocket and raw TCP application-protocol profiles beyond HTTP keepalive
- IPv6 and provider-network VIPs
- active member failure/recovery while under load
- externally located generators for a true Internet-edge/FIP campaign
- statistical confidence intervals and regression thresholds suitable for CI gating

## Troubleshooting Ansible role resolution

If Ansible reports an error such as:

```text
the role 'common' was not found in .../playbooks/roles
```

run from the repository root and confirm the active configuration and role path:

```bash
.venv/bin/ansible-config dump --only-changed | grep -i roles
ls -ld roles/common roles/backend roles/locust
.venv/bin/ansible-playbook playbooks/configure.yml --syntax-check -e @config/local.yml
```

The repository `ansible.cfg` must contain:

```ini
[defaults]
roles_path = ./roles
```

If you invoke Ansible from another working directory, either `cd` to the repository root first or set `ANSIBLE_CONFIG=/path/to/octavia-perf-tool/ansible.cfg`.

### Resilient baseline campaigns

`scripts/run_baseline_suite.sh` creates the campaign LB once and treats failure of that initial provisioning as recoverable. By default it captures failed-LB diagnostics, cleans up the failed object, and retries creation up to three total attempts. Once the persistent LB exists, scenario failures are isolated to the listener/pool/member/health-monitor resources; cleanup removes those children while retaining the Amphora so later scenarios can continue. See `docs/USAGE.md` for the full lifecycle, artifact names, pause workflow, and retry controls.

## Combined comparison after separate flavor suites

If you run `scripts/run_baseline_suite.sh` once per Octavia flavor, you do not need to rerun the benchmarks together to compare them. Keep the result directories under `results/` and run:

```bash
make campaign-report
```

This creates `results/campaign-comparison/` with a concise `README.md`, a detailed scenario-by-scenario report, CSV scorecards, and overview/per-scenario charts. The first chart to open is `results/campaign-comparison/charts/composite-dashboard.png`: a single presentation-ready view containing overall flavor performance, scenario wins, the all-scenario performance and p99-latency matrices, run-to-run variability, and flavor-scoped direct-nginx efficiency where available. The default selection uses the latest three successful runs per flavor/scenario so older history is not silently mixed into a current four-flavor comparison.

For an explicit set and reference flavor:

```bash
.venv/bin/python scripts/compare_campaigns.py results \
  --flavor flavor-a --flavor flavor-b --flavor flavor-c --flavor flavor-d \
  --reference-flavor flavor-a
```

See `docs/USAGE.md` for report semantics, selection controls, fingerprint checks, and generated artifacts.

### One-flavor suite identity and verified LB flavor

The canonical baseline runbook runs one Octavia flavor at a time. Use `FLAVOR=<name>` explicitly when the config lists multiple Octavia flavors. If the config has exactly one flavor, omitting `FLAVOR` uses that configured value; the runbook no longer silently falls back to `amphora-default`.

Each suite gets a `suite_id` shared by its direct controls and Octavia runs. Direct controls carry `baseline_for_flavor` for provenance while remaining `target_kind=direct`. Persistent LB creation resolves the requested Octavia flavor to a UUID and verifies the created LB's `flavor_id` before benchmark traffic begins. Combined campaign reports keep legacy unscoped direct controls separate rather than assigning them to a flavor implicitly.

