# Amphora / HAProxy Performance Tuning and Diagnostics

This document captures the first performance checks to make when an Octavia Amphora reaches a much lower HTTP request rate than expected from HAProxy itself.

## 1. Distinguish two Octavia logging controls

These settings do different things:

```yaml
conf:
  octavia:
    amphora_agent:
      disable_local_log_storage: true
    haproxy_amphora:
      connection_logging: false
```

`amphora_agent.disable_local_log_storage` prevents logs from being stored on the Amphora filesystem. It does **not** disable HAProxy tenant connection/flow logging.

`haproxy_amphora.connection_logging: false` is the Octavia option that disables generated HAProxy connection logging.

The upstream Octavia default for `connection_logging` is `true`, so an OpenStack-Helm deployment that sets only `disable_local_log_storage: true` can still generate the HAProxy flow-log messages.

As of the Genestack `main` base override checked on 2026-08-26, `conf.octavia.amphora_agent.disable_local_log_storage: true` is present, but no base `haproxy_amphora.connection_logging` override is present. Environment-specific overrides may still set it, so verify the effective Helm values and rendered `octavia.conf`.

For OpenStack-Helm / Genestack the value path is:

```yaml
conf:
  octavia:
    haproxy_amphora:
      connection_logging: false
```

Before changing it, inspect the effective configuration in the running worker/controller pod:

```bash
kubectl -n openstack exec deploy/octavia-worker -c octavia-worker -- \
  awk '
    /^\[haproxy_amphora\]/{show=1; print; next}
    /^\[/{if(show) exit}
    show{print}
  ' /etc/octavia/octavia.conf
```

If the deployment name/container name differs, locate it first:

```bash
kubectl -n openstack get pods | grep octavia
```

Also inspect Helm's effective values:

```bash
helm -n openstack get values octavia -a | \
  grep -n -A8 -B4 -E 'haproxy_amphora|connection_logging|disable_local_log_storage'
```

After changing controller-side `connection_logging`, create a new load balancer or force a configuration regeneration before comparing performance. Verify the generated Amphora HAProxy config rather than assuming the value took effect.

## 2. Listener connection limits used by this harness

The harness deliberately uses two listener limits:

```yaml
octavia:
  listener:
    connection_limit: 100000
    capacity_connection_limit: 1000000
```

`connection_limit` is used for Locust RPS, max-RPS, churn/CPS-like, and bandwidth scenarios. `capacity_connection_limit` is used only by the simultaneous connection-capacity engine.

This avoids carrying a 1,000,000-connection HAProxy `maxconn` into every normal request-rate test while still ensuring connection-capacity tests are not capped by listener policy.

Both applied values are written into the run manifest.

## 3. Verify the generated HAProxy config

Inside the Amphora, find the running command/config:

```bash
sudo pgrep -af haproxy
PID=$(pgrep -xo haproxy)
sudo tr '\0' ' ' < /proc/$PID/cmdline
echo
```

Then inspect the generated configuration:

```bash
sudo grep -nE \
  '(^global|^defaults|^frontend|^backend|^[[:space:]]+(log|maxconn|nbthread|cpu-map|option|http-reuse|timeout|balance))' \
  /var/lib/octavia/*/haproxy.cfg
```

For current Octavia HTTP listeners, verify expected connection-reuse/keepalive behavior such as:

```text
option http-keep-alive
http-reuse safe
```

Unexpected `httpclose`, `forceclose`, or `http-server-close` settings are worth investigating for a keepalive benchmark.

Record the HAProxy build/version:

```bash
haproxy -vv
```

## 4. Run the Amphora diagnostic helper

Copy `scripts/amphora_perf_check.sh` onto the Amphora and run it as root before and during a loaded interval:

```bash
sudo ./amphora_perf_check.sh
```

For a short sampled view during load:

```bash
sudo SAMPLE_SECONDS=15 ./amphora_perf_check.sh
```

The helper captures:

- HAProxy version and command line;
- CPU count/model;
- HAProxy process/thread CPU;
- rsyslog/keepalived/amphora-agent CPU;
- softirq and interrupt distribution;
- networking/file-descriptor sysctls;
- generated HAProxy tuning lines;
- HAProxy runtime `show info` output when a stats socket and `socat`/`nc` are available.

Useful runtime fields include `Nbthread`, `CurrConns`, `ConnRate`, `SessRate`, `MaxSessRate`, and `Idle_pct`.

## 5. Current one-vCPU interpretation

A one-vCPU Amphora must share that CPU across:

```text
HAProxy
Linux TCP/IP stack
virtio/OVN packet processing
softirq/IRQ work
amphora-agent
keepalived
rsyslog (if active)
other OS work
```

This differs materially from HAProxy sizing tests that dedicate one CPU to HAProxy while other CPUs process network interrupts/kernel work.

When guest vCPU utilization is ~100% but libvirt vCPU scheduler delay remains near zero, the guest is genuinely CPU-bound rather than being starved by the hypervisor.

## 6. Amphora image checks

For new performance flavors, build a current Noble/current-release Amphora image and record:

```bash
cat /etc/os-release
haproxy -vv
uname -a
```

Octavia supports a CPU-pinning image mode for multi-vCPU Amphorae. Enable it during image creation with the current Octavia `diskimage-create.sh` CPU-pinning option (`-m`, equivalent to `AMP_ENABLE_CPUPINNING=1` in releases that expose that variable).

The intended layout is roughly:

```text
vCPU 0  -> kernel / interrupts / OS
vCPU 1+ -> isolated HAProxy worker CPUs
```

This is not expected to help a one-vCPU flavor, but it should be part of the 2/4/8-vCPU performance-flavor A/B matrix.

## 7. Virtio multiqueue and SDN path

For multi-vCPU Amphora flavors, evaluate Nova virtio multiqueue:

```bash
openstack flavor set \
  --property hw:vif_multiqueue_enabled=true \
  <amphora-compute-flavor>
```

Do not assume multiqueue plus CPU pinning is automatically optimal; benchmark both combinations because the Octavia CPU-pinning image intentionally controls IRQ placement.

If normal virtio/OVN networking becomes the ceiling, Octavia SR-IOV Amphora networking is a later performance tier to test. Keep SR-IOV results separate from the normal virtual-network datapath.

## 8. Persistent-Amphora benchmark workflow

For image/flavor tuning campaigns, use the baseline runbook's persistent-LB mode so the same Amphora VM is retained across the scenario suite. The harness rebuilds only listener/pool/member/health-monitor resources between scenarios. This avoids mixing Amphora placement changes into protocol or workload comparisons.

For an experimental flavor that must be disabled after initial use:

```bash
PAUSE_AFTER_LB_CREATE=1 \
FLAVOR=my-experimental-flavor \
./scripts/run_baseline_suite.sh
```

Disable the flavor only after the runbook reports that the persistent LB/amphora is ready. The remaining scenarios reuse that existing Amphora.

## 9. Recommended A/B sequence

Change one variable at a time:

1. Current 1-vCPU baseline.
2. Confirm `haproxy_amphora.connection_logging=false`; rerun unchanged workload.
3. Use 100k listener `connection_limit` for normal RPS/CPS tests; keep 1M only for capacity tests.
4. Verify/rebuild current Noble + current-release Amphora image if stale.
5. Compare a standalone 1-vCPU HAProxy VM on the same aggregate/network to isolate Octavia-specific overhead.
6. Benchmark 2-vCPU CPU-pinned Amphora.
7. Benchmark 4-vCPU CPU-pinned Amphora; A/B virtio multiqueue.
8. Evaluate SR-IOV only after the standard datapath is understood.

Do not mix these changes into one benchmark result; each change should have its own manifest/fingerprint population.

