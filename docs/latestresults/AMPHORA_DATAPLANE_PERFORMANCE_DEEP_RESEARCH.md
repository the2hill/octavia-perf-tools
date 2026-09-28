# Amphora Dataplane Performance Engineering: Below the Product/API Layer

## September 18, 2026 evidence update

The September 18 campaign provides the strongest evidence so far that the current multiqueue Amphora dataplane scales materially better than the earlier single-queue configuration. The standard flavor-matrix populations are now fully reconciled. Elite HTTP has three homogeneous standard-fingerprint runs at **89,687.7 / 93,180.9 / 94,680.4 RPS** (median **93,180.9 RPS**), while the later 500->4000-user Elite-only diagnostic uses a different fingerprint and remains a separate population.

### Normal-staircase results

The unfiltered `comparison-summary.csv` contains four Elite HTTP rows because it combines the three-run standard flavor-matrix suite with the later Elite-only concurrency diagnostic. For the normal matrix below, Elite HTTP is therefore recalculated from the three matching standard-suite/fingerprint runs only. Values below are staircase peak-RPS observations, not adaptive sustainable ceilings.

| Scenario | Lite | Plus | Pro | Elite | Elite/Pro | Elite p99 | Elite payload | Quality note |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| HTTP 1-KiB keepalive | 13,470 | 16,112 | 57,309 | **93,181** | **1.63x** | 130 ms | 0.763 Gb/s | Homogeneous 3-run standard-matrix population; 0 failures and no validity/bottleneck warnings. |
| TLS passthrough 1-KiB keepalive | 25,930 | 23,221 | 72,766 | **140,975** | **1.94x** | 98 ms | 1.155 Gb/s | 0 Elite failures, but **2/3 Elite runs have resource warnings**. |
| TLS termination 1-KiB keepalive | 9,920 | 12,248 | 40,779 | **73,892** | **1.81x** | 160 ms | 0.605 Gb/s | 0 Elite failures; no resource warnings. |
| TLS termination + re-encryption | 10,330 | 14,323 | 47,634 | **64,592** | **1.36x** | 180 ms | 0.529 Gb/s | Elite: 3,892 total failures; Lite/Plus/Pro: millions of failures at their reported peaks. |

These are `peak_rps_history`/`median_peak_rps` staircase results and therefore must not be presented as equivalent to adaptive `max_sustainable_rps`. They are useful as workload-specific observed envelopes. All four rows now use homogeneous normal-matrix populations. The TLS-passthrough result deserves special caution: zero failures coexist with resource warnings in two of three Elite runs, so ~141k is not yet a clean ceiling.

The latest aggregate also provides `median_peak_payload_gbps` for these 1-KiB tests. That is useful dataplane evidence, but it is not the same as a dedicated 64-KiB or 1-MiB bandwidth-capacity test.

### Adaptive HTTP reference

The separate clean three-run Elite `http_1k_max_rps` set remains approximately:

```text
median sustainable RPS: 127,756
range:                  126,363 - 129,163
best p99:                6 ms
accepted failures:       0%
generator limited:       false
generator CPU hot:       false
validity warnings:       none
```

This remains a strong, repeatable evidence point for the multiqueue Elite dataplane. The homogeneous September standard-matrix HTTP median is **~93.2k RPS** across three matching runs; the separate concurrency diagnostic peaked at **126.7k RPS** and is analyzed below. The adaptive and staircase datasets answer different questions and should not be merged into one product limit. The earlier ~137k run remains a higher observed point but is not treated as the clean ceiling because all eight generators hit 100% CPU.

### Updated engineering interpretation

1. The earlier ~58k Pro/Elite plateau was a **configuration-dependent dataplane result**, not a fundamental 8-vCPU Amphora ceiling. Enabling virtio multiqueue and validating queue/HAProxy-thread distribution unlocked a much larger Elite envelope. The clean adaptive Elite result is ~127.8k sustainable RPS. The homogeneous September HTTP matrix median is **~93.2k RPS**, while the separate Elite concurrency staircase peaks at 126.7k and shows where offered concurrency stops increasing throughput.

2. **HAProxy worker distribution is healthy.** The observed Elite process has seven worker threads mapped one-to-one onto CPUs 1-7, with roughly 88-89% process CPU per thread during the observed heavy-load interval. This argues against one HAProxy worker being the immediate limiting resource.

3. **Backend virtio is also healthy.** The rebuilt/checked backend fleet exposes four combined queues and four active RX/TX queue pairs on its 4-vCPU guests. The benchmark backend path is therefore not suffering from the same single-queue defect found in the old Amphora configuration.

4. **The two-housekeeping-CPU experiment remains interesting but is no longer the first priority.** The clean ~128k adaptive Elite result establishes a stable baseline. The user-scaling staircase should first show where CPU0, HAProxy workers, latency, or client/backend resources become limiting before sacrificing a HAProxy worker to a second housekeeping CPU.

5. **TLS request-rate is now measured; TLS handshake/CPS behavior is the next optimization surface.** The Elite normal staircase measured ~141.0k RPS for passthrough, ~73.9k for frontend termination, and ~64.6k for termination plus backend re-encryption. Plain HTTP in the same homogeneous matrix measured ~93.2k RPS. The remaining TLS uncertainty is primarily full-handshake CPS, resumed-session behavior, connection reuse, OpenSSL behavior, and quality-gated sustainable limits rather than whether TLS termination can scale at all.

6. **Product capacity should be scenario-specific and metric-specific.** The homogeneous September populations show Elite is ~1.63x Pro for plain HTTP, ~1.94x for passthrough, ~1.81x for termination, but only ~1.36x for re-encryption. Separately, the clean adaptive HTTP benchmark is ~2.12x Pro. A single global “2x RPS” claim would therefore be too broad without specifying workload and benchmark method.

---

## Executive conclusions

The next material gains in the Amphora offering are unlikely to come from adding more product-level flavor sizes by themselves. The strongest current evidence says the problem has moved down into the data path: CPU topology, interrupt and softirq placement, virtio/vhost parallelism, HAProxy thread/listener behavior, TLS crypto cost, host NUMA/network locality, and shared-host contention.

The most important conclusions are:

1. **The earlier 4-vCPU versus 8-vCPU plateau was configuration-dependent.** After virtio multiqueue was enabled and verified, the clean Elite adaptive HTTP result rose to a median ~127.8k sustainable RPS across three runs. The September standard matrix measured **~93.2k plain-HTTP RPS**, ~141.0k TLS-passthrough RPS, ~73.9k TLS-termination RPS, and ~64.6k re-encryption RPS for Elite. The separate concurrency diagnostic independently peaked at 126.7k and maintained roughly 122k median RPS through 1500 users before degrading at higher concurrency. The current evidence therefore supports real vertical scaling once the virtio datapath is parallelized.

2. **The current ~128k clean Elite reference is no longer generator-limited.** The three adaptive Elite runs reported `generator_limited=false`, `generator_cpu_hot=false`, and no validity warnings. The prior ~137k run is retained as a higher observed point but excluded from the primary ceiling because all eight generators were CPU-hot. The next diagnostic is therefore about server-side resource behavior rather than recovering basic client headroom.

3. **Octavia's supported CPU-pinning image is intentionally asymmetric.** With `diskimage-create.sh -m`, Octavia isolates all guest vCPUs except the first, removes `irqbalance`, sets IRQ affinity to the first CPU, enables `nohz_full` on the isolated CPUs, and has the Amphora agent pin HAProxy workers to vCPU1 and above.[^2] This is a sensible low-jitter design, but it deliberately creates a single housekeeping CPU. That makes vCPU0 saturation a predictable failure mode at sufficiently high PPS/CPS.

4. **Virtio multiqueue is necessary to test, but merely exposing queues is not enough.** Nova documents that virtio-net defaults to a single queue pair, that multiqueue can scale network throughput with vCPU count, and that the guest must activate the queues with `ethtool -L` or equivalent persistent configuration.[^3] In an Octavia CPU-pinned image, however, the upstream IRQ policy may still concentrate interrupt processing on CPU0. Therefore queue count, queue activation, and per-queue IRQ affinity must all be verified independently.

5. **The most promising Amphora-specific experiment is not “8 vCPU versus 4 vCPU”; it is “one housekeeping CPU versus a larger housekeeping budget.”** If CPU0 remains saturated after generator headroom is fixed and multiqueue is verified, compare the upstream model (`CPU0=kernel/IRQ`, `CPU1..N=HAProxy`) against a controlled experimental image that reserves two guest CPUs for kernel/IRQ/virtio work and leaves the remainder for HAProxy. Another branch is to retain one housekeeping CPU while selectively using RPS/RFS/XPS. Both approaches trade HAProxy worker count for packet-processing parallelism and must be measured rather than assumed.

6. **HAProxy 2.8 itself contains a relevant scaling knob that deserves an A/B test: listener sharding.** HAProxy 2.8 added `tune.listener.default-shards`; multiple listener sockets reduce kernel-side contention when many threads compete on one listening socket. The default strategy is by thread group.[^4] On an Amphora with only one thread group, that may still mean a single shard. It is not the first knob to change while vCPU0 is a suspected softirq bottleneck, but it is a legitimate second-stage test for high connection rates and TLS CPS.

7. **The Noble image changes the TLS discussion.** OpenStack 2025.1 changed the default Amphora base image to Ubuntu Noble, and Noble currently supplies HAProxy 2.8.16 linked against OpenSSL 3.x (`libssl3`).[^5][^6] HAProxy Technologies' more recent SSL-stack testing found significant full-handshake scaling differences between OpenSSL 3.x and alternative crypto stacks on large multicore systems.[^7] Those exact benchmark numbers cannot be projected onto an AMD EPYC Amphora, but they are strong evidence that the TLS library must be treated as part of the dataplane, not an invisible implementation detail.

8. **TLS capacity must be characterized separately from HTTP RPS.** DigitalOcean's current capacity unit publishes 10k RPS and 10k concurrent connections per node, but also only 250 new SSL connections/sec with ordinary certificates and 50/sec with RSA-4096.[^8] That fivefold difference is a useful public demonstration that certificate/key choices can dominate TLS connection-rate economics. Rackspace should benchmark RSA-2048, RSA-4096, and ECDSA separately, and distinguish full handshakes, resumed sessions, and requests on persistent TLS connections.

9. **Backend connection reuse is a real performance lever and is already aligned with Octavia's HAProxy template.** Octavia deliberately enabled `http-reuse safe` and HTTP keepalive because upstream testing showed increased HTTP request rates.[^9] DigitalOcean independently exposes backend keepalive and says it generally improves RPS, latency, and resource efficiency, while warning it is not universally beneficial.[^10] This should remain in the baseline fingerprint and not be accidentally changed between flavor tests.

10. **Do not cargo-cult Linux sysctl recipes.** Some HAProxy tuning guides still recommend values such as `tcp_tw_reuse=1`; current Linux documents a different default/semantic and explicitly says it should not be changed without expert guidance.[^11][^12] The correct approach is to instrument listen queues, SYN backlog, TIME_WAIT, ephemeral-port pressure, drops, retransmits, and file-descriptor use, then change only the variable that is demonstrably limiting the workload.

11. **NUMA locality and host network locality belong in the baseline for premium flavors.** Nova explicitly supports network NUMA affinity for provider and tunneled networks, and requires a guest NUMA topology for that affinity to matter.[^13] For 4- and 8-vCPU premium Amphorae that fit within one host NUMA node, `hw:numa_nodes=1` plus verified memory/NIC/tunnel locality should be considered a baseline candidate, not a post-failure tweak.

12. **The Standard/Pro/Elite design should be retained, but the dataplane tests decide how much isolation each tier really needs.** Standard can remain shared VCPU at a tested 4-6 allocation ratio; Pro is still the strongest commercial candidate for Nova `mixed` CPU policy; Elite remains the fully dedicated control. The economic objective is the number of Amphorae per physical host that continue to meet the tier's customer-visible performance floor, not the highest isolated-host RPS.[^14]

13. **A production density limit must be based on correlated load, not Placement arithmetic.** A ratio of 6 may be entirely healthy when 20% of Amphorae are busy and unacceptable when 75-100% burst simultaneously. The host-density campaign must measure per-Amphora RPS/p99 together with physical CPU, run queue, softirq, vhost/QEMU workers, OVN/OVS, NIC PPS, drops, and memory pressure.[^14]

14. **The near-term sequence should now pivot from request-rate characterization to the remaining scenario dimensions:** preserve the current multiqueue keepalive matrix and the Elite concurrency-saturation diagnostic as the baseline; then run current-MQ connection-churn/CPS, simultaneous-connection, and dedicated-bandwidth campaigns with explicit quality gates. The September rebuild script did not include those scenario families. Only after those data exist should listener sharding, connection reuse, TLS-stack work, or a two-housekeeping-CPU A/B be prioritized against a concrete bottleneck. The multiqueue fix should remain the production baseline for all future flavor comparisons.

---

### Elite 500->4000-user HTTP concurrency diagnostic

The rebuild campaign included a separate Elite-only `http_1k_keepalive` run with fingerprint `36c2a02206267288`. It used six 60-second stages at 500, 750, 1000, 1500, 2000, and 4000 users. This population must remain separate from the standard flavor-matrix fingerprint.

Using the `Aggregated` rows from `locust_stats_history.csv`:

| Users | Median RPS | Peak RPS | Median p95 | Median p99 | Max observed p99 | Failures |
|---:|---:|---:|---:|---:|---:|---:|
| 500 | **121,042.3** | 126,340.6 | 5 ms | 6 ms | 8 ms | 0 |
| 750 | **122,244.5** | **126,722.8** | 8 ms | 9 ms | 9 ms | 0 |
| 1,000 | **122,460.9** | 124,071.3 | 9 ms | 10 ms | 11 ms | 0 |
| 1,500 | **122,022.9** | 123,217.0 | 13 ms | 15 ms | 17 ms | 0 |
| 2,000 | **117,906.4** | 123,437.4 | 19 ms | 22 ms | 23 ms | 0 |
| 4,000 | **108,535.5** | 115,411.2 | 42 ms | 56 ms | 59 ms | 0 |

The important result is the shape, not merely the 126.7k peak. The 500-1500 user stages form an approximately 121-122.5k RPS plateau, with the absolute peak occurring at 750 users. Increasing offered concurrency to 2000 users reduces median throughput by about 3.7% versus the 1000-user stage while doubling the observed median p99 from 10 ms to 22 ms. At 4000 users, median throughput is about 11.4% lower than at 1000 users while median p99 rises to 56 ms. No request failures were recorded across the entire 42,935,645-request run.

This indicates that for this 1-KiB keepalive workload, the useful saturation region is already reached around 750-1500 concurrent Locust users. Higher offered concurrency mainly consumes latency headroom rather than increasing request throughput. The whole-run summary's 41 ms p99 is less informative for this purpose than the per-stage history because it blends all six concurrency levels together.

# 1. Scope

This report intentionally stays below the cloud product and API layer. It does not propose replacing Amphora with another Octavia provider and does not treat OVN Octavia as the direction of travel. The objective is to improve the existing Amphora/HAProxy offering on a dedicated OpenStack compute cluster.

The relevant stack is:

```text
client/load generator
    |
    v
physical network / NIC
    |
    v
host Linux networking + IRQ/softirq
    |
    v
OVN/OVS / tap / vhost-net
    |
    v
virtio-net queues in Amphora
    |
    v
guest IRQ / NAPI / softirq / TCP-IP
    |
    v
HAProxy listener / scheduler / worker thread
    |
    v
backend connection / virtio / host datapath
    |
    v
member
```

Performance is constrained by the narrowest serial or shared stage in that path. Aggregate guest CPU can look healthy while one interrupt CPU, one listener socket, one virtqueue, one host NIC queue, or one crypto path is saturated.

This report therefore focuses on:

- HAProxy 2.8 thread scheduling, affinity, and listener sharding;
- Octavia's CPU-pinning image behavior;
- virtio-net queues and guest IRQ/softirq placement;
- host QEMU/vhost and Linux packet-processing load;
- NUMA, cache, memory, and physical-NIC locality;
- TLS handshakes and crypto-library behavior;
- logging and connection-reuse overhead;
- Linux connection/backlog/file-descriptor tuning;
- NIC offloads and busy polling;
- CPU frequency, C-states, SMT, and AMD EPYC topology;
- shared-host density and correlated customer traffic;
- how public operators and large HAProxy users validate these tradeoffs.

---

# 2. Current evidence: the problem is already below the flavor layer

## 2.1 Earlier 1-vCPU baseline

The earlier 1-vCPU / 4-GiB Amphora work established a useful reference point:

- direct nginx capacity was roughly 87k RPS;
- the highest observed passing Octavia HTTP result was roughly 11.1k RPS;
- the high-concurrency plateau was roughly 8.2-8.4k RPS;
- the guest vCPU reached essentially 100%;
- libvirt scheduling delay was tiny;
- the small 1-KiB workload was well below the VIF bandwidth policy ceiling.[^15]

That was important because it ruled out the simplest explanations. The one-vCPU result behaved like a genuine guest-compute ceiling rather than a backend or hypervisor entitlement problem.

## 2.2 The newer 4-vCPU versus 8-vCPU result is more important

The later `http_1k_max_rps` campaign found:

| Metric | Pro: 4 vCPU | Elite: 8 vCPU |
|---|---:|---:|
| Median sustainable RPS | 57,487.9 | 57,978.5 |
| Difference | - | +0.85% |
| Median accepted p99 | 11 ms | 11 ms |
| Median failure rate | 0% | 0% |
| Median peak Amphora CPU cores | 3.156 | 4.510 |
| Median normalized guest CPU | 78.9% | 56.4% |
| Hottest guest vCPU | 99.98% | 99.97% |
| Peak RX PPS | ~110.4k | ~110.5k |
| Peak TX PPS | ~113.4k | ~113.0k |
| Median vCPU scheduling delay | 0.000417 s/s | 0.000472 s/s |

The 0.85% median advantage was smaller than normal run-to-run variation. Doubling vCPU count did not materially move throughput, even though the 8-vCPU guest had substantially more aggregate CPU headroom.[^1]

This is exactly the kind of pattern that warrants per-CPU and per-queue investigation.

## 2.3 Do not overstate the conclusion yet

The generators were also near CPU saturation, with worker peaks generally in the 93-99% range.[^1] The correct interpretation is therefore:

> There is clear evidence of a hot-vCPU condition inside the Amphora, but the measured ~58k RPS ceiling may be a co-limit between Amphora and generator capacity.

The next run should increase generator VMs while leaving the server-side datapath unchanged. A clean diagnosis requires:

```text
generator CPU comfortably below saturation
        +
direct nginx substantially above Octavia
        +
Octavia CPU0 still pinned near 100%
        =
strong Amphora/dataplane bottleneck evidence
```

This sequencing matters. Tuning the guest before removing the generator ceiling risks attributing an improvement or regression to the wrong component.

---

# 3. Octavia CPU pinning: why vCPU0 is special

Octavia's `cpu-pinning` diskimage element was added specifically to improve vertical scaling. When enabled with `diskimage-create.sh -m` (or the equivalent environment variable), it does four important things on a multi-vCPU Amphora:[^2]

1. isolates all guest vCPUs except the first;
2. uninstalls `irqbalance` and sends IRQ affinity to the first CPU;
3. applies a customized TuneD latency/network profile;
4. sets `nohz_full=1-N` and has the Amphora agent pin HAProxy workers onto the isolated vCPUs.

Conceptually:

```text
vCPU0
  kernel
  interrupts
  NAPI / softirq
  TCP/IP
  virtio processing
  general OS housekeeping

vCPU1..N
  HAProxy worker threads
  deliberately isolated from most kernel noise
```

This is a strong design for keeping HAProxy workers predictable. It also creates an intentionally finite housekeeping budget.

## 3.1 Why this can become a vertical-scaling wall

Suppose a 4-vCPU Amphora has:

```text
CPU0: kernel / packet processing
CPU1: HAProxy worker
CPU2: HAProxy worker
CPU3: HAProxy worker
```

At low and medium load, adding HAProxy workers can scale request processing. At some point, however, all three workers depend on CPU0 delivering packets, TCP work, and socket events fast enough. If CPU0 reaches 100% while CPUs1-3 retain headroom, another HAProxy worker cannot fix the bottleneck.

The 8-vCPU version can make this more obvious:

```text
CPU0: one housekeeping CPU
CPU1-7: seven HAProxy CPUs
```

If the packet path still funnels through CPU0, HAProxy worker capacity may increase by more than 2x while packet-delivery capacity barely changes.

That is consistent with the current symptom, though it is not yet proven.

## 3.2 Exact evidence to collect

During a stable max-RPS step, capture at one-second resolution where possible:

```bash
mpstat -P ALL 1
cat /proc/interrupts
cat /proc/softirqs

ps -eLo pid,tid,psr,pcpu,comm,args --sort=-pcpu | head -100

haproxy -vv

grep -RniE 'nbthread|thread-group|cpu-map|tune.listener|shards' \
  /var/lib/octavia /etc/haproxy 2>/dev/null
```

The key correlation is not simply “CPU0 is busy.” It is:

```text
CPU0 user/system/softirq utilization
+ NET_RX / NET_TX softirq growth
+ virtio interrupt distribution
+ queue-specific packet counters
+ HAProxy worker CPU
+ RPS/p99
```

If CPU0 reaches 100% primarily in `%soft` while HAProxy worker CPUs remain below saturation, the network housekeeping hypothesis becomes very strong.

If CPU0 is instead high in HAProxy user time, inspect thread affinity/configuration because HAProxy may not actually be pinned as expected.

---

# 4. Virtio-net multiqueue: expose, activate, then verify distribution

Nova documents that virtio-net normally presents one transmit/receive queue pair. Multiqueue allows multiple queue pairs and is specifically useful when a VM has multiple vCPUs and many active connections. Nova also warns that multiqueue increases CPU consumption.[^3]

The flavor/image capability is only the first step:

```bash
openstack flavor set <flavor> \
  --property hw:vif_multiqueue_enabled=true
```

Inside the guest, Nova documents enabling the queues with:

```bash
ethtool -L <dev> combined <N>
```

where `N` is normally chosen in relation to guest vCPU count.[^3]

## 4.1 Three states must be distinguished

### State A: multiqueue not exposed

```text
ethtool -l ethX
Maximums: Combined: 1
```

No amount of guest affinity tuning can parallelize that virtio receive path.

### State B: multiqueue exposed but only one queue active

The virtual device supports several queues, but the guest is still using one effective pair. This is a common false-positive configuration: the flavor says multiqueue, so operators assume it is working.

### State C: multiple queues active, but IRQs still converge on CPU0

This state is particularly relevant to Octavia's CPU-pinning image. More virtqueues exist, but if the image intentionally forces their interrupts to CPU0, the packet-processing work can remain concentrated.

The important inference is:

> **queue count is not the same as CPU parallelism.**

## 4.2 Required guest checks

```bash
for nic in $(ls /sys/class/net | grep -v '^lo$'); do
  echo "===== $nic channels ====="
  ethtool -l "$nic"
  echo "===== $nic stats ====="
  ethtool -S "$nic" 2>/dev/null | head -200
  echo "===== $nic features ====="
  ethtool -k "$nic"
done

cat /proc/interrupts

for f in /proc/irq/*/smp_affinity_list; do
  printf '%s: ' "$f"
  cat "$f"
done

for f in /sys/class/net/*/queues/rx-*/rps_cpus; do
  printf '%s: ' "$f"
  cat "$f"
done

for f in /sys/class/net/*/queues/tx-*/xps_cpus; do
  printf '%s: ' "$f"
  cat "$f"
done
```

Also collect per-queue packet/drop counters before and after the load interval.

## 4.3 Recommended A/B order

Do not immediately spread all network processing over all CPUs. That would defeat the isolation model before proving it is necessary.

Use this sequence:

```text
A. upstream CPU-pinning behavior + current queue state
B. same image, multiqueue definitely activated
C. multiqueue + measured/controlled queue-to-CPU affinity
D. if CPU0 still limits, two-housekeeping-CPU image
E. alternatively, one housekeeping CPU + selective RPS/RFS/XPS
```

Each state must be its own benchmark fingerprint.

---

# 5. RSS, RPS, RFS, and XPS: what they can and cannot fix

Linux provides several mechanisms for distributing packet-processing work:[^16]

- **RSS**: hardware receive-side scaling across NIC queues/CPUs;
- **RPS**: software receive packet steering;
- **RFS**: steers receive processing toward the CPU running the application flow;
- **XPS**: transmit packet steering.

In a bare-metal web server these can be tuned to keep packet processing close to the application thread. Amphora is different because the upstream image deliberately separates packet housekeeping from HAProxy worker CPUs.

## 5.1 The locality-versus-isolation tradeoff

Two competing designs are plausible.

### Isolation-first

```text
CPU0        all IRQ/network stack
CPU1..N     HAProxy only
```

Benefits:

- HAProxy worker CPUs see very little kernel noise;
- predictable cache behavior;
- simple mental model.

Risk:

- CPU0 becomes the global PPS ceiling.

### Flow-locality model

```text
RX queue 0 -> CPU1 -> HAProxy thread 1
RX queue 1 -> CPU2 -> HAProxy thread 2
...
```

Benefits:

- more packet-processing parallelism;
- potential cache locality between stack and application.

Risks:

- softirq work steals time from HAProxy workers;
- more interprocessor interrupts or cross-CPU handoffs;
- more tuning complexity;
- can perform worse if steering and application affinity disagree.

Neither model should be assumed superior for this workload.

## 5.2 Strong recommendation

Do **not** enable broad guest RPS masks such as “all CPUs” as a baseline tweak. First prove CPU0 softirq saturation. If it is real, compare controlled masks and the two-housekeeping-CPU model.

A good experiment on an 8-vCPU guest would be:

```text
Upstream:
  CPU0      housekeeping
  CPU1-7    HAProxy

Experimental H2:
  CPU0-1    housekeeping / virtio / softirq
  CPU2-7    HAProxy

Experimental distributed:
  CPU0      base housekeeping
  selected RX queues/RPS mapped to CPU1-2
  CPU3-7    HAProxy
```

The test should report not only maximum RPS, but RPS per guest CPU consumed and p99/p999 latency.

---

# 6. HAProxy 2.8 threading and CPU affinity

Ubuntu Noble's current package is HAProxy 2.8.16 on amd64.[^6] That matters because tuning advice for HAProxy 3.2/3.3 may not apply.

HAProxy's threading architecture gives each thread its own scheduler; an individual session's entities are processed by one thread at a time.[^17] Modern HAProxy normally uses multiple worker threads and can scale well, but shared structures and listener/socket contention can still create non-linear behavior.

## 6.1 Validate Octavia's generated CPU map before changing it

The first question is not “what should `cpu-map` be?” It is “what did Octavia actually generate?”

Capture:

```bash
haproxy -vv

grep -RniE \
  '(^|[[:space:]])(nbthread|thread-groups|cpu-map|tune.listener.default-shards|shards)' \
  /var/lib/octavia /etc/haproxy 2>/dev/null

ps -eLo pid,tid,psr,pcpu,comm,args | grep -E 'haproxy|PID'
```

For an `-m` image, expect worker threads to be pinned to isolated guest CPUs rather than floating across all vCPUs.[^2]

If that is not true, fix the image/agent behavior before testing manual HAProxy affinity.

## 6.2 Thread count should not exceed useful CPU

HAProxy's own performance guidance warns that excessive threads relative to actual CPU/topology can reduce performance through sharing and synchronization overhead. Modern releases also pay attention to cache/NUMA locality.[^18]

For Amphora this reinforces a simple rule:

> Do not treat `nbthread` as a knob that creates capacity independently of physical CPU entitlement.

A 7-thread HAProxy whose seven guest CPUs are overcommitted onto a busy shared host is not equivalent to seven dedicated cores.

## 6.3 Listener sharding is a real HAProxy 2.8 test candidate

HAProxy 2.8 added `tune.listener.default-shards`. The motivation is that many threads pulling new connections from one listening socket can create kernel and polling contention. Multiple sockets bound to the same address/port let the kernel distribute incoming connections and reduce cross-thread overhead.[^4]

HAProxy documents policies including:

```text
by-process
by-thread
by-group
```

and recommends caution with excessive per-thread sockets.[^19]

For a small 4- or 8-vCPU Amphora, an experimental `by-thread` or small explicit shard count is reasonable **after** the guest queue/IRQ bottleneck is understood.

Why not first?

Because listener sharding optimizes connection acceptance among HAProxy threads. It does not solve a CPU0 that is saturated processing virtio/NAPI/TCP work before HAProxy receives the event.

## 6.4 Use connection-rate workloads to evaluate sharding

Listener sharding is most likely to show value in:

- TCP connection churn;
- HTTP `Connection: close` tests;
- TLS full-handshake CPS;
- many short-lived connections.

It may show little value in a keepalive test where a relatively small number of connections carry many requests.

Therefore do not judge it only with `http_1k_max_rps` keepalive.

---

# 7. HTTP keepalive and backend reuse

OpenStack intentionally changed the Amphora HAProxy template years ago to enable kernel TCP splicing for high-rate TCP and to use safe HTTP backend connection reuse because these increased request rate and lowered CPU overhead.[^9]

For HTTP listeners, verify the generated config includes expected semantics such as:

```text
option http-keep-alive
http-reuse safe
```

## 7.1 Why backend reuse matters

Without reuse, a high client-side request rate can create a comparable backend connection rate. That drives:

- SYN/SYN-ACK processing;
- ephemeral-port use;
- TIME_WAIT state;
- backend accept overhead;
- more conntrack entries/transitions;
- more packet/interrupt work.

With safe connection reuse, multiple client transactions can use established backend connections where HAProxy's safety rules allow it.

DigitalOcean exposes the same concept to customers and states that backend keepalive generally improves RPS, latency, and resource efficiency, while acknowledging workloads where it can increase latency.[^10]

## 7.2 Do not casually change `http-reuse safe`

HAProxy supports more aggressive reuse modes, and aggressive reuse may reduce connection-setup cost further. But stronger reuse policies have behavioral tradeoffs and can increase the chance of sending a new request to a backend connection that is about to close.

For a managed public service, `safe` is a sound baseline. If `aggressive` is ever tested, make it an isolated experimental scenario with realistic backends and retries, not a hidden production default.

---

# 8. TCP splice and protocol-specific paths

Octavia enabled HAProxy's TCP kernel splicing because it can reduce CPU overhead on very high-rate TCP load balancers.[^9]

That creates an important benchmarking rule:

> HTTP, TCP passthrough, TLS passthrough, TLS termination, and TLS re-encryption are different datapaths and must not share one performance number.

A TCP passthrough workload may spend far more time in efficient forwarding paths, while TLS termination adds crypto and HTTP mode adds parsing/routing work.

Keep separate benchmark populations for:

```text
TCP passthrough, long-lived
TCP connection churn
HTTP keepalive
HTTP connection-close
TLS passthrough
TLS termination -> HTTP backend
TLS termination -> HTTPS backend (re-encryption)
```

This is also the right way to find whether CPU0 saturation belongs to packet processing generally or to one protocol path.

---

# 9. TLS: likely the largest uncharacterized CPU variable

## 9.1 Requests per second is not TLS capacity

A single TLS connection can carry one request or tens of thousands of requests. These two workloads can show the same HTTP RPS while imposing radically different cryptographic cost.

At minimum, report three TLS regimes:

### Persistent TLS

```text
few handshakes
many HTTP requests per established TLS connection
```

Measures HTTP/proxy efficiency once crypto setup is amortized.

### Resumed TLS

```text
high connection rate
session ticket/session resumption available
```

Measures a common production optimization.

### Full TLS handshake

```text
new connection
no reusable TLS session
key exchange/signature work each time
```

Measures worst-case new-connection capacity and often exposes crypto-library scaling.

## 9.2 DigitalOcean provides a useful public warning

DigitalOcean currently says each HTTP LB node adds:[^8]

- up to 10,000 RPS;
- up to 10,000 simultaneous connections;
- 250 new SSL connections/sec with ordinary certificates;
- only 50 new SSL connections/sec with RSA-4096.

This should influence how Amphora SKUs are characterized. A generic statement such as “supports 50k RPS” tells a customer very little about a certificate-heavy API workload that creates thousands of new TLS sessions per second.

## 9.3 Noble + HAProxy 2.8 + OpenSSL 3 deserves explicit measurement

Ubuntu Noble's HAProxy package depends on `libssl3`, placing the current default image on the OpenSSL 3 generation.[^6]

HAProxy Technologies' 2025 SSL-stack study reported that OpenSSL 3.x scaling, especially OpenSSL 3.0 in their high-core-count test, could be materially below OpenSSL 1.1.1 and AWS-LC for full TLS connection establishment and session resumption.[^7]

Important caveats:

- the public benchmark used different hardware and much larger thread counts than an Amphora;
- some results were on ARM/Graviton systems;
- HAProxy and crypto-library builds differed;
- the result does **not** prove Noble is a production bottleneck on AMD EPYC.

But it absolutely justifies collecting:

```bash
haproxy -vv
openssl version -a
openssl speed ...
```

and treating the TLS library/version as part of the benchmark fingerprint.

## 9.4 Recommended TLS matrix

For each candidate flavor:

| Test | Certificate | Session behavior | What it isolates |
|---|---|---|---|
| TLS-persistent | RSA-2048 | persistent connection | proxy/HTTP after handshake |
| TLS-CPS-full | RSA-2048 | resumption disabled | common full-handshake cost |
| TLS-CPS-full | RSA-4096 | resumption disabled | worst-case RSA cost |
| TLS-CPS-full | ECDSA P-256 | resumption disabled | modern signature path |
| TLS-CPS-resume | RSA/ECDSA | tickets/resumption | resumed-session scaling |
| TLS-reencrypt | same frontend matrix | HTTPS backend | double-ended crypto cost |

Track:

- successful handshakes/sec;
- failed handshakes;
- p50/p95/p99 handshake latency;
- per-vCPU utilization;
- HAProxy thread CPU;
- crypto-library CPU symbols with `perf` on an isolated test environment if permitted;
- packets/sec and bytes/sec;
- session reuse rate.

## 9.5 Future image branch: newer HAProxy / alternate TLS stack

Do not replace Noble's supported HAProxy/OpenSSL packages merely because a vendor benchmark looks faster.

Instead, if TLS CPS becomes a commercial limiter, create a separate research branch:

```text
Baseline: Noble distro HAProxy 2.8 + distro OpenSSL 3
Candidate A: newer supported HAProxy package, same OpenSSL family
Candidate B: HAProxy build with AWS-LC or another supported high-performance stack
```

Require security-patching, packaging, Octavia template/agent compatibility, FIPS implications, and lifecycle support before considering production.

---

# 10. Logging: a direct per-connection tax

Octavia's current documentation says disabling tenant flow logging can improve Amphora load-balancing performance and recommends it alongside disabling local log storage when the operator accepts the observability/security tradeoff.[^20]

The relevant controls are separate:

```ini
[amphora_agent]
disable_local_log_storage = True

[haproxy_amphora]
connection_logging = False
```

`disable_local_log_storage` is not equivalent to disabling HAProxy connection logs. The latter is the direct per-connection/per-request dataplane variable.

## 10.1 Benchmark logging in three states

```text
A. current production behavior
B. connection_logging=False
C. B + local log storage disabled, if operationally acceptable
```

Record:

- sustainable RPS/CPS;
- p99;
- CPU0 and HAProxy worker CPU;
- rsyslog CPU;
- disk writes;
- log message rate/bytes;
- any offload queue/backpressure.

## 10.2 Why this can matter even without disk writes

HAProxy still formats and emits logging data before the logging stack transports or discards it. High-rate flow logging can therefore consume CPU and memory bandwidth even when logs are shipped remotely.

This is why logging state must be in every result fingerprint. It should never silently differ between two flavor comparisons.

---

# 11. NUMA, cache, memory, and network locality

For a packet-processing VM, “which CPU?” is incomplete. The meaningful question is:

```text
Which CPU core
on which NUMA node
near which memory
near which physical/tunnel NIC
with which cache domain?
```

Nova supports network NUMA affinity. For provider networks, operators can associate physnets with NUMA nodes; for tunneled networks, `[neutron_tunnel] numa_nodes` can describe the host NUMA node(s) associated with the tunnel endpoint. Nova notes that the guest needs a NUMA topology for these constraints to matter.[^13]

## 11.1 Premium baseline

For a 4- or 8-vCPU Amphora that comfortably fits within one host NUMA node:

```bash
openstack flavor set <flavor> --property hw:numa_nodes=1
```

Then verify, do not assume:

```bash
virsh vcpupin <domain>
virsh numatune <domain>
virsh dumpxml <domain> | sed -n '/<numatune>/,/<\/numatune>/p'

QPID=$(pgrep -f "qemu.*<domain>" | head -1)
numastat -p "$QPID"
grep -E 'Cpus_allowed_list|Mems_allowed_list' /proc/$QPID/status

cat /sys/class/net/<host-nic>/device/numa_node
```

## 11.2 What to look for

Bad pattern:

```text
vCPU threads       NUMA0
QEMU memory        mostly NUMA1
physical NIC       NUMA1
```

or:

```text
vCPU/HAProxy       NUMA0
host tunnel NIC    NUMA1
softirq            NUMA1 CPUs
```

These layouts introduce remote memory/interconnect traffic before HAProxy even becomes the interesting bottleneck.

## 11.3 AMD EPYC 7003 implications

The current benchmark history references AMD EPYC 75F3-class hosts. AMD's EPYC 7003 tuning material describes NPS (NUMA Nodes Per Socket) as a latency/bandwidth tradeoff and recommends beginning with NPS1 for network applications, then evaluating NPS2/NPS4 for latency-sensitive/high-speed networking workloads.[^21]

Do **not** change NPS globally based on a DPDK tuning guide alone; Amphora uses a virtualized kernel/virtio path, not a DPDK dataplane. But record the BIOS NPS topology because it determines what “one NUMA node” means to Linux and influences memory/cache/NIC locality.

---

# 12. Host QEMU, vhost-net, and kernel worker placement

Red Hat's virtualization guidance explicitly calls out `vhost_net` and virtio multiqueue as major VM network-performance mechanisms.[^22]

In this architecture, guest CPU pinning does not make host-side packet processing free. Track:

- QEMU emulator threads;
- vhost kernel threads;
- host tap/vnet activity;
- host softirq CPUs;
- OVN/OVS processes;
- physical NIC IRQ CPUs.

## 12.1 Emulator threads

For dedicated/mixed premium flavors, Nova supports:

```text
hw:emulator_threads_policy=share
```

which moves emulator overhead to the shared CPU pool rather than consuming the guest's dedicated PCPU budget.[^23]

This is attractive for the Pro/Elite design, provided `cpu_shared_set` has real headroom.

A premium host can therefore be divided conceptually as:

```text
host/Kubernetes/OVN/NIC housekeeping CPUs
Nova dedicated PCPU pool
Nova shared VCPU + emulator pool
```

The mistake is to reserve PCPUs carefully for guests while leaving all QEMU/vhost/OVN/IRQ work fighting on one tiny housekeeping set.

## 12.2 Inspect real host threads during load

```bash
ps -eLo pid,tid,psr,pcpu,comm,args --sort=-pcpu | \
  egrep 'qemu|vhost|ovs|ovn|ksoftirqd' | head -200

pidstat -t -p <qemu-pid> 1
mpstat -P ALL 1
cat /proc/softirqs
cat /proc/interrupts
```

Do not assume `hw:emulator_threads_policy=share` controls every kernel worker associated with vhost. Observe affinity and CPU consumption directly.

---

# 13. Physical NIC RSS and host IRQ placement

Linux RSS distributes receive queues across CPUs so that one CPU does not have to process every packet.[^16] Red Hat similarly recommends multiple queues to relieve a single CPU interrupt bottleneck and stresses CPU/IRQ locality.[^24]

The physical NIC side should be audited before increasing Amphora density.

## 13.1 Host checks

```bash
ethtool -l <nic>
ethtool -x <nic> 2>/dev/null
ethtool -S <nic>
ethtool -k <nic>

cat /proc/interrupts
cat /proc/softirqs

for irq in $(awk '/<nic-pattern>/{gsub(":", "", $1); print $1}' /proc/interrupts); do
  printf 'IRQ %s affinity: ' "$irq"
  cat /proc/irq/$irq/smp_affinity_list
done
```

Record:

- RX/TX queue count;
- IRQ-to-CPU map;
- packet distribution by queue;
- drops/missed packets/no-buffer counters;
- per-CPU NET_RX/NET_TX softirq;
- NIC PPS and Gbps.

## 13.2 Avoid two extremes

Bad extreme 1:

```text
all NIC IRQs -> one host housekeeping CPU
```

This can cap the whole host regardless of Nova CPU entitlement.

Bad extreme 2:

```text
NIC IRQs -> premium guest PCPUs
```

This steals cycles from the very CPUs sold as isolated customer capacity.

The dedicated cluster should have a measured host-housekeeping budget large enough for physical NIC, OVN/OVS, kernel networking, QEMU/vhost, Kubernetes/node agents, and other host work.

---

# 14. NIC offloads: preserve them until evidence says otherwise

Linux and virtio commonly use:

- TSO: TCP Segmentation Offload;
- GSO: Generic Segmentation Offload;
- GRO: Generic Receive Offload;
- checksum offloads.

These reduce per-packet CPU overhead by batching work. Kernel and Red Hat documentation describe GRO/GSO/TSO as fundamental throughput mechanisms, and Red Hat notes that disabling GRO can significantly reduce TCP receive throughput.[^25]

Therefore:

> Do not disable GRO/GSO/TSO as a generic “low latency” optimization on the Amphora path.

Benchmark them only if there is a specific symptom such as latency/jitter, packet-size pathology, capture/encapsulation interaction, or known driver bug.

The report should capture `ethtool -k` for both guest and host interfaces so offload-state drift does not contaminate comparisons.

---

# 15. Busy polling: a latency experiment, not a default

Linux supports NAPI busy polling, allowing an application/kernel receive path to poll for packets rather than waiting for an interrupt. This can reduce latency at the cost of continuously burning CPU.[^26]

That tradeoff is generally hostile to a dense multi-tenant Standard tier.

Potential use:

- controlled Elite latency experiment;
- dedicated CPUs;
- tail-latency-sensitive workload;
- demonstrated interrupt/wakeup latency problem.

Poor use:

- cluster-wide default;
- Standard density pool;
- attempt to fix a throughput problem without proving wakeup latency is the limiter.

If tested, include host power consumption and CPU-idle residency because “better p99” may come from simply refusing to let CPUs sleep.

---

# 16. CPU frequency, C-states, and AMD determinism

High-performance networking is sensitive not only to CPU allocation but to how quickly a core wakes and what frequency it sustains.

AMD's EPYC material notes the density/performance tradeoff in C-state policy and exposes platform determinism settings; Red Hat TuneD also has `network-latency` and `network-throughput` style profiles that make different CPU/power/memory tradeoffs.[^27][^28]

## 16.1 Recommended approach

### Standard

Prioritize host economics. Do not disable every C-state or SMT feature globally unless testing proves a customer-visible problem.

### Pro/Elite

A/B:

```text
current BIOS / governor
vs
performance-oriented governor/profile
vs
reduced deep C-state residency
```

Measure:

- sustainable RPS/CPS;
- p99/p999;
- run-to-run variance;
- host watts if available;
- all-core frequency under sustained load;
- idle-to-burst behavior.

The product question is not merely “which profile is fastest?” It is:

> Does the extra power/capacity cost purchase a performance consistency improvement customers will pay for?

## 16.2 SMT

For Nova dedicated CPUs, `hw:cpu_thread_policy=isolate` prevents other guests from sharing sibling threads of a physical core, improving isolation at the cost of host capacity.[^29]

Test at least:

```text
Elite-A: dedicated + SMT prefer/default
Elite-B: dedicated + thread_policy=isolate
```

Do not disable SMT across the whole physical cluster before this comparison. The expensive question is how much p99/variance improves per physical core stranded.

---

# 17. Huge pages and memory behavior

Huge pages can reduce TLB pressure, and NFV guidance commonly includes them in high-performance VM profiles. They also create a statically managed memory pool and can increase fragmentation/operational complexity.[^30]

For a relatively small HAProxy appliance, the benefit is not guaranteed.

Recommended matrix:

```text
Standard: 4K pages baseline
Pro:      4K vs 2 MiB A/B
Elite:    4K vs 2 MiB A/B
1 GiB:    research only unless a strong measured reason appears
```

Track not only throughput but:

- p99/p999;
- CPU cycles/request if available;
- TLB-miss counters with `perf stat` in a controlled environment;
- host memory fragmentation;
- schedulable Amphora count after hugepage reservation.

Do not trade away host flexibility for a sub-percent benchmark improvement.

---

# 18. Linux socket/backlog/sysctl tuning: instrument before modifying

High connection-rate proxies can be limited by:

- listen backlog;
- SYN backlog;
- file descriptors;
- ephemeral source ports for backend connections;
- TIME_WAIT accumulation;
- socket memory;
- conntrack table capacity;
- packet backlog/drop queues.

But most “HAProxy sysctl lists” were written against older kernel defaults.

## 18.1 Example: `somaxconn`

Current Linux documents a default `net.core.somaxconn` of 4096 on modern kernels and points operators to `tcp_max_syn_backlog` as a related control.[^12]

Before increasing it, measure:

```bash
ss -lnt
ss -s
nstat -az
netstat -s 2>/dev/null
cat /proc/net/netstat
```

Look specifically for listen overflow/drop counters and SYN retransmission behavior.

## 18.2 Example: `tcp_tw_reuse`

HAProxy Enterprise tuning material still shows `net.ipv4.tcp_tw_reuse=1` for high outgoing connection rates.[^11]

Current kernel documentation says:

```text
0 = disabled
1 = globally enabled
2 = loopback only
```

and warns not to change the setting without expert guidance; the documented default is 2.[^12]

That is a perfect illustration of why old sysctl recipes should not be pasted into a current Noble image.

If backend source-port exhaustion is observed, first quantify:

```bash
ss -tan state time-wait | wc -l
sysctl net.ipv4.ip_local_port_range
nstat -az | egrep -i 'retrans|listen|timewait|overflow'
```

Then evaluate backend connection reuse and source-address/port capacity before changing global TCP semantics.

## 18.3 File descriptors and `maxconn`

HAProxy adjusts file-descriptor requirements based on `maxconn`, but enormous listener limits are not free from a capacity-planning perspective.[^31]

The benchmark harness is correct to separate:

```text
normal RPS/CPS tests:      100k listener connection limit
connection capacity test:  1M listener connection limit
```

Keep connection limits above the workload being tested but do not force a million-connection configuration into every request-rate benchmark.

---

# 19. Conntrack and the SDN path

Stateful virtual networking can introduce connection tracking outside the Amphora. In an OVN/OVS environment, packet processing may involve host kernel conntrack and Open vSwitch/OVN flows depending on the security/network path.

Do not assume HAProxy owns all connection state.

At host saturation tests, collect:

```bash
sysctl net.netfilter.nf_conntrack_count
sysctl net.netfilter.nf_conntrack_max

conntrack -S 2>/dev/null || true

ovs-vsctl show
ovs-ofctl dump-ports <bridge> 2>/dev/null
```

and the deployment-specific OVN/OVS metrics already available in monitoring.

Watch for:

- conntrack insert failures;
- table-full events;
- OVS/OVN CPU growth;
- datapath misses;
- packet drops;
- increasing CPU cost as flow count grows.

This is especially important in connection-churn campaigns. A keepalive RPS test may create relatively few new flows and completely miss a conntrack/CPS ceiling.

---

# 20. HAProxy observability that should be captured per run

HAProxy's runtime information should become part of the benchmark evidence rather than an ad-hoc debugging step.

Useful fields include:

```text
Nbthread
CurrConns
CumConns
ConnRate
ConnRateLimit
MaxConnRate
SessRate
MaxSessRate
Idle_pct
Maxconn
Uptime_sec
```

Also capture frontend/backend CSV stats where possible:

- current/max sessions;
- connection totals;
- request totals;
- queue depth;
- retries/redispatches;
- response errors;
- connection errors;
- bytes in/out.

A max-RPS result without HAProxy's own view of `Idle_pct`, connection rate, and session counters leaves too much ambiguity.

---

# 21. DigitalOcean: the useful below-the-API lessons

DigitalOcean remains the most relevant public contrast because its historical product was also a per-customer proxy-VM design.

## 21.1 Their old vertical curve proves multi-CPU proxying can scale

DigitalOcean's 2020 synthetic HTTPS benchmark reported roughly:[^32]

| LB | CPU | HTTPS RPS |
|---|---:|---:|
| Small | 1 | 8.3k |
| Medium | 2 | 23.9k |
| Large | 4 | 41.9k |

The benchmark is not directly comparable to Octavia, but it demonstrates a production operator obtaining useful vertical scaling from 1 to 4 proxy CPUs.

This makes the current Amphora 4-vCPU/8-vCPU flat result more likely to represent a correctable data-path constraint than an inherent “HAProxy does not scale” property.

## 21.2 DigitalOcean explicitly separated cheap packet forwarding from expensive HTTP/TLS work

When redesigning for much larger scale, DigitalOcean wrote that the compute needs of its L4 NLB tier are “orders of magnitude less” than an HTTP load balancer because the latter must terminate TCP, perform TLS handshakes, process HTTP headers, and more.[^33]

That is directly relevant even though the goal here is Amphora improvement: it confirms that the expensive capacity units we need to characterize are exactly TCP connection handling, TLS, and HTTP processing.

## 21.3 Active proxy nodes and DSR are architecture differences, not tuning targets

DigitalOcean now uses BGP/ECMP into bare-metal Katran/XDP nodes, then active-active LB Droplets, with DSR for egress. Their front L4 layer can saturate a 50-Gbps NIC with little CPU in their testing.[^33]

That is not something a stock Amphora flavor can reproduce through sysctls. Use it as a boundary condition when comparing public performance numbers.

## 21.4 Backend keepalive is an operator-confirmed efficiency lever

DigitalOcean says enabling backend keepalive generally improves RPS, latency, and resource efficiency because the LB can reuse fewer established backend TCP connections.[^10]

That independently supports preserving Octavia's `http-reuse safe` behavior and explicitly fingerprinting backend reuse in all HTTP tests.

## 21.5 Their product publishes TLS CPS separately

DigitalOcean's node limits explicitly separate RPS, concurrent connections, and new SSL CPS.[^8] This is the product-level reflection of the lower-level reality described in this report.

For Amphora, the equivalent engineering scorecard should include:

```text
HTTP keepalive RPS
TLS passthrough RPS
TLS termination RPS
TLS termination + re-encryption RPS
HTTP close / TCP CPS
TLS full-handshake CPS
TLS resumed CPS
simultaneous connection capacity
payload Gbps
p99/p999 at each supported envelope
```

Current evidence status after the September 18 campaign and the latest supplied aggregate:

| Dimension | Status in this report |
|---|---|
| HTTP keepalive RPS | **Measured for Lite / Plus / Pro / Elite**. Elite standard-matrix median is **93.2k RPS** across three matching runs (89.7k / 93.2k / 94.7k); the separate concurrency diagnostic peaks at 126.7k, and the separate adaptive Elite reference remains ~127.8k sustainable. |
| TLS passthrough RPS | **Measured for all four flavors**; Elite median peak is 141.0k, but 2/3 Elite runs have resource warnings, so it is not yet a clean ceiling. |
| TLS termination RPS | **Measured for all four flavors**; Elite median peak 73.9k with 0 failures/resource-warning runs in the aggregate. |
| TLS termination + re-encryption RPS | **Measured for all four flavors**; Elite median peak 64.6k with 3,892 total failures; lower-tier peaks carry millions of failures and are not quality-gated capacity points. |
| 1-KiB observed payload rate | **Measured as part of the core request-rate runs**: Elite standard-matrix medians are **0.763 / 1.155 / 0.605 / 0.529 Gb/s** for HTTP / passthrough / termination / re-encryption respectively. |
| HTTP close / TCP CPS-like churn | **Not part of the September rebuild campaign; current-MQ reference still required**. |
| TLS full-handshake CPS-like churn | **Not part of the September rebuild campaign; current-MQ reference still required**. |
| Simultaneous connection capacity | **Not part of the September rebuild campaign; current-MQ reference still required**. |
| Dedicated 64-KiB/1-MiB bandwidth ceilings | **Not part of the September rebuild campaign; current-MQ reference still required**. The 1-KiB payload rates above are not substitutes. |

Older pre-MQ churn figures remain useful as historical evidence but should not be used as the current Amphora reference envelope because the multiqueue change materially altered scaling.

---

# 22. LinkedIn: a modern HAProxy operator lesson

A 2025 HAProxyConf case study summarized by HAProxy Technologies describes LinkedIn replacing a heavily customized Apache Traffic Server edge design with HAProxy after comparative benchmarking. In LinkedIn's test, using a 1-KiB payload and simulated 1-ms upstream delay, the threshold was the point where end-to-end average latency exceeded 10 ms. The vendor summary reports ATS crossing that threshold around 4.5k RPS, Envoy around 13k, and HAProxy remaining below it to roughly 55k RPS.[^34]

The exact number is not an Amphora target. The useful lessons are methodological:

1. **define a latency boundary, not merely a maximum offered load;**
2. **use the same payload and upstream delay across candidates;**
3. **stop counting a throughput point as useful once latency violates the service objective;**
4. **software architecture can dominate hardware scaling.** LinkedIn reportedly saw only a modest fleet reduction after moving its legacy stack to newer 64-core AMD hardware, which helped motivate changing the proxy architecture/software rather than just buying larger machines.[^34]

That maps well to the current Amphora situation: an 8-vCPU guest with a saturated serial path is not solved by continuing to add cores.

---

# 23. Benchmark methodology: measure a performance envelope, not a peak

## 23.1 Every result needs a workload fingerprint

Record at minimum:

```text
Octavia release / provider
Amphora image ID + build provenance
Ubuntu release
kernel version
HAProxy version/build flags
OpenSSL version
Nova flavor + extra specs
CPU policy + thread policy
host CPU model / BIOS NPS
host governor / power profile
NUMA placement
virtio queue maximum + active count
IRQ affinity
RPS/RFS/XPS masks
HAProxy nbthread / cpu-map / listener shards
connection logging state
listener maxconn
HTTP reuse mode
TLS cert/key type
TLS session-resumption policy
backend count
payload size
keepalive/close behavior
generator topology
traffic path
host placement
```

Without this, the campaign can produce statistically precise comparisons of two different systems.

## 23.2 Use medians and variance, but also inspect the limiting resource

Three repetitions are a reasonable exploratory floor. Compare:

- median primary result;
- min/max;
- coefficient of variation;
- p99/p999;
- errors;
- limiting CPU/queue/resource state.

A 5% RPS improvement with 8% run variance is not a product result.

## 23.3 The result is valid only if the load generator has headroom

For max-RPS testing, use the existing target of approximately:

```text
preferred generator peak CPU: <= 70-75%
exploratory upper bound:       < 80-85%
invalid/ambiguous:             repeated > 85%
```

The present 93-99% generator CPU is too close to saturation for clean ceiling attribution.[^1]

---

# 24. Recommended experiment program

## Phase 0 - Remove benchmark ambiguity

**Goal:** prove the test harness can exceed the Amphora.

Actions:

1. increase generator VMs from 4 to 8 while keeping per-VM process density unchanged;
2. rerun direct nginx and `http_1k_max_rps`;
3. require generator CPU headroom;
4. retain the same backend, path, image, and flavor.

Exit condition:

```text
direct path materially above Octavia
AND generator CPU not hot
```

If Octavia rises proportionally with the extra generators, the previous result was client-limited and the dataplane diagnosis must be updated.

---

## Phase 1 - Prove the hot-vCPU mechanism

**Goal:** determine what consumes vCPU0.

Collect during load:

```text
mpstat per CPU
/proc/interrupts
/proc/softirqs
virtio queue count
per-queue packet counters
IRQ affinity
RPS/XPS masks
HAProxy thread CPU + PSR
HAProxy runtime info
```

Decision:

```text
CPU0 mostly softirq + virtio interrupts
    -> queue/IRQ/housekeeping branch

CPU0 mostly HAProxy user CPU
    -> affinity/configuration branch

all HAProxy workers saturated
    -> normal aggregate HAProxy CPU ceiling

host vhost/OVN/NIC CPUs saturated first
    -> host dataplane branch
```

---

## Phase 2 - Virtio and housekeeping A/B

For 4-vCPU and 8-vCPU test flavors:

```text
A  current upstream -m image behavior
B  multiqueue exposed + proven active
C  B + controlled queue/IRQ distribution
D  B + two housekeeping guest CPUs
E  B + selective RPS/RFS/XPS
```

Primary outputs:

- sustainable RPS;
- p99/p999;
- hottest-vCPU utilization;
- aggregate guest cores consumed;
- packets per housekeeping CPU;
- HAProxy `Idle_pct`;
- guest drops/errors.

The winning design is not necessarily the highest RPS. Prefer the design with the best performance per physical CPU and stable tail latency.

---

## Phase 3 - HAProxy listener/connection-path A/B

Only after Phase 2 is understood:

```text
A  current HAProxy 2.8 listener sharding behavior
B  experimental tune.listener.default-shards by-thread
C  controlled explicit shard count if template support permits
```

Run against:

- HTTP keepalive;
- HTTP close;
- TCP churn;
- TLS full-handshake CPS.

If sharding improves CPS but not keepalive RPS, that is expected and useful.

---

## Phase 4 - Logging A/B

```text
A current logging
B connection_logging=False
C B + disable_local_log_storage=True (if acceptable)
```

Keep image/flavor/network placement constant.

---

## Phase 5 - TLS matrix

Run the certificate/session matrix from Section 9 for 2-, 4-, and 8-vCPU candidates after the packet path is stable.

This phase should answer:

```text
Does TLS CPS scale with HAProxy workers?
Does CPU0 remain the ceiling?
Does OpenSSL dominate worker CPU?
What certificate choice most affects sellable capacity?
Does re-encryption halve the useful CPS class or less/more?
```

---

## Phase 6 - Host locality and power

A/B premium candidates across:

```text
NUMA unconstrained vs hw:numa_nodes=1
verified local vs remote-ish host placement where safely reproducible
current governor vs performance profile
SMT prefer/default vs isolate
4K vs 2M pages
```

This is where Elite's consistency proposition should be proven.

---

## Phase 7 - Standard host-density campaign

Do not use one Amphora per host.

For VCPU allocation ratios:

```text
4.0
5.0
6.0
```

populate one or more hosts to realistic target density and drive:

```text
25% of Amphorae hot
50% hot
75% hot
100% hot
```

Run at least:

- HTTP keepalive RPS;
- TLS termination;
- connection churn;
- bandwidth/payload scenario.

Measure per-Amphora distribution, not just aggregate host throughput.

The decisive statistics are:

```text
minimum / p10 Amphora throughput
median throughput
p99 latency distribution across Amphorae
run-to-run variance
host CPU run queue
vCPU delay/steal
softirq CPU
NIC PPS/drops
vhost/QEMU CPU
OVN/OVS CPU
```

This campaign sets the real Standard `max_instances_per_host` and safe allocation ratio.

---

## Phase 8 - Pro mixed versus Elite dedicated

Use a common 4-vCPU example first:

```text
Pro-A: mixed, dedicated mask 0
Pro-B: mixed, dedicated mask 0-1
Pro-C: mixed, dedicated mask 0-2
Elite: dedicated all vCPUs
```

The commercial question is:

> What is the smallest PCPU footprint that preserves the desired fraction of Elite performance and tail-latency consistency under contention?

If Pro-B consumes two PCPU + two shared VCPU and delivers nearly the same SLO-compliant throughput as four dedicated PCPU, it is a substantially better service-margin design even if Elite remains slightly faster.

---

# 25. Telemetry checklist

## 25.1 Amphora guest

### CPU

```text
per-vCPU user/system/softirq/irq/idle
load average and run queue
frequency if visible
context switches
```

### Interrupt/network

```text
/proc/interrupts
/proc/softirqs
ethtool -l / -S / -k
queue packet/drop counters
IRQ affinity
RPS/XPS masks
```

### TCP/kernel

```text
ss -s
nstat
netstat -s
socket memory
TIME_WAIT count
listen overflows/drops
retransmits
```

### HAProxy

```text
Nbthread
Idle_pct
CurrConns
ConnRate
SessRate
MaxSessRate
frontend/backend sessions
retries
connection errors
queue depth
bytes
```

### Local services

```text
rsyslog CPU
keepalived CPU
amphora-agent CPU
logging rate
```

---

## 25.2 Hypervisor host

### CPU/scheduler

```text
per-CPU utilization
run queue
QEMU thread CPU
vhost worker CPU
ksoftirqd
frequency/C-state where available
```

### NUMA

```text
vCPU pinning
QEMU memory placement
NIC NUMA node
host tunnel NIC NUMA node
remote NUMA allocation counters
```

### Network

```text
physical NIC Gbps
PPS
per-queue counters
IRQ affinity
RX/TX drops
ring/no-buffer counters
OVN/OVS CPU
flow/conntrack pressure
```

---

## 25.3 Generator/backend

Never omit them from the evidence package:

```text
generator per-VM and per-process CPU
source connection count / ephemeral-port pressure
backend CPU
backend network
backend active connections
backend errors
```

A “load balancer ceiling” is only trustworthy after these are ruled out.

---

# 26. Prioritized engineering recommendations

## P0 - Do now

| Item | Why |
|---|---|
| Increase generator fleet and rerun direct + Octavia controls | Removes current 93-99% client CPU ambiguity |
| Verify the deployed image was actually built with `-m` | Multi-vCPU results are not interpretable otherwise |
| Record `haproxy -vv`, OpenSSL version, generated `nbthread/cpu-map` | Establishes actual software/thread state |
| Verify virtio multiqueue maximum **and active** queues | Flavor metadata alone is insufficient |
| Capture guest per-vCPU `mpstat`, interrupts and softirqs during load | Determines whether CPU0 is packet-path constrained |
| Capture HAProxy runtime stats per run | Shows whether HAProxy itself is idle/connection-limited |
| Capture host vhost/QEMU/softirq/NIC queue telemetry | Prevents moving a bottleneck from guest to host invisibly |

## P1 - High-value A/B tests

| Item | Why |
|---|---|
| Two-housekeeping-CPU experimental image | Direct response to the present hot-vCPU symptom |
| Multiqueue + controlled IRQ/queue affinity | Determines whether packet processing can scale without sacrificing all worker isolation |
| `connection_logging=false` | Upstream Octavia explicitly says it can improve LB performance |
| HAProxy 2.8 listener sharding | Potential high-CPS/accept-path gain available in deployed HAProxy generation |
| `hw:numa_nodes=1` for premium flavors | Keeps small dataplane VM within one NUMA locality domain |
| `hw:emulator_threads_policy=share` with adequate shared CPU pool | Protects paid PCPU capacity from emulator overhead |
| TLS cert/session matrix | Converts unknown TLS cost into a sellable capacity envelope |

## P2 - Product-tier optimization

| Item | Why |
|---|---|
| Pro mixed masks 0 / 0-1 / 0-2 | Finds best PCPU margin/performance point |
| Elite SMT `prefer` vs `isolate` | Quantifies isolation benefit versus stranded capacity |
| Performance power profile / C-state A/B | May reduce tail latency and variance for premium tier |
| 2 MiB hugepages A/B | Possible TLB/jitter benefit, but must justify fragmentation |
| Selective RPS/RFS/XPS | Useful only after queue/softirq evidence supports it |
| Host NIC RSS/IRQ remap | Important as density increases; must preserve premium PCPU isolation |

## P3 - Separate research tracks

| Item | Why |
|---|---|
| Newer HAProxy / alternate TLS library image | Potential major TLS-CPS upside, but large support/security lifecycle decision |
| Busy polling | Can trade CPU/power for latency; poor default for dense service |
| 1-GiB hugepages | High fragmentation cost for uncertain Amphora benefit |
| SR-IOV / OVS-DPDK | Changes architecture/operational model; not required to optimize current virtio Amphora offering |

---

# 27. Anti-patterns to avoid

## 27.1 “8 vCPU is faster than 4 vCPU because it has more cores”

Current data already disproves this assumption for the present path. Find the serial resource first.[^1]

## 27.2 “Multiqueue is enabled in the flavor, therefore traffic is multiqueued”

Nova explicitly requires guest activation. Then IRQ distribution still needs verification.[^3]

## 27.3 “Spread all IRQs across all CPUs”

That can destroy the isolation Octavia's `-m` image was designed to create. Change the topology only after proving CPU0 is the bottleneck.

## 27.4 “Use every performance sysctl from a blog”

Kernel defaults and semantics change. `tcp_tw_reuse` is the canonical example.[^11][^12]

## 27.5 “Disable GRO/TSO/GSO for lower latency”

That often sacrifices TCP throughput and raises CPU consumption. Preserve offloads unless the measured workload shows a reason not to.[^25]

## 27.6 “Force hugepages and SMT isolation on every tier”

Both can reduce schedulable density. Premium features need customer-visible benefits that exceed their capacity cost.

## 27.7 “Validate allocation ratio 6 with one busy Amphora”

That proves nothing about a statistically multiplexed commercial service. The test must load multiple colocated Amphorae simultaneously.[^14]

## 27.8 “Use RPS as the only SKU number”

RPS, TLS CPS, concurrent state, bandwidth/PPS, and tail latency stress different resources. DigitalOcean and other operators expose multiple capacity dimensions for this reason.[^8]

## 27.9 “Treat ACTIVE_STANDBY standby compute as throughput capacity”

The standby is a resiliency resource, not normal active dataplane capacity. Capacity planning must preserve failover reserve separately.

---

# 28. Recommended immediate next run

Given the evidence available today, the best next run is intentionally narrow.

## Step 1: remove generator ambiguity

Increase the current 4 generator VMs to 8 while keeping the same VM flavor and roughly one Locust worker process per vCPU.[^1]

Do not change:

```text
Amphora image
Octavia flavor
backend count
payload
traffic path
generator network mode
HTTP keepalive semantics
logging state
```

Run:

```text
direct nginx control
4-vCPU Pro http_1k_max_rps
8-vCPU Elite http_1k_max_rps
```

## Step 2: collect synchronized guest telemetry

During the accepted high-load step:

```bash
mpstat -P ALL 1
cat /proc/interrupts
cat /proc/softirqs

for nic in $(ls /sys/class/net | grep -v '^lo$'); do
  ethtool -l "$nic"
  ethtool -S "$nic" 2>/dev/null
  ethtool -k "$nic"
done

ps -eLo pid,tid,psr,pcpu,comm,args --sort=-pcpu | head -100

haproxy -vv
```

and query HAProxy runtime stats at one-second or low-frequency intervals that do not materially disturb the run.

## Step 3: decide the next branch from evidence

### Result A

```text
Octavia still ~58k
Direct >> 58k
CPU0 ~100% softirq/IRQ
HAProxy worker CPUs have headroom
```

**Next:** multiqueue/IRQ/housekeeping campaign.

### Result B

```text
Octavia still ~58k
Direct >> 58k
CPU0 HAProxy user CPU high
```

**Next:** inspect generated `cpu-map`, thread assignment, listener sharding, and any serial HAProxy path.

### Result C

```text
Octavia climbs materially above 58k
Generator CPU now healthy
```

**Next:** previous ceiling was partly generator-limited; establish the new true Amphora ceiling before tuning.

### Result D

```text
Direct remains near Octavia and generators are still hot
```

**Next:** increase generator capacity again. Do not touch Amphora yet.

### Result E

```text
host vhost/softirq/NIC/OVN saturates before guest
```

**Next:** host dataplane tuning and density-pool design, not guest HAProxy tuning.

---

# 29. What success should look like

The goal is not a heroic one-off benchmark. The desired engineering outcome is a repeatable mapping such as:

```text
Standard
  shared VCPU
  ratio 4-6 depending on validated occupancy
  defined minimum/reference RPS, TLS CPS, connections and bandwidth
  known p99 degradation at target host density

Pro
  mixed PCPU + VCPU
  dedicated housekeeping + selected HAProxy CPU(s)
  near-Elite sustained performance
  materially better physical-host density than full PCPU

Elite
  dedicated PCPU
  verified single-NUMA locality
  strongest tail-latency consistency
  highest TLS/CPS and RPS envelope
  explicit premium for capacity consumed
```

The underlying technical target is:

```text
SLO-compliant customer throughput
---------------------------------
physical host resources consumed
```

That is the metric that aligns HAProxy tuning, Nova placement, host networking, and commercial margin.

---

# 30. Final assessment

The current evidence does not suggest that Amphora or HAProxy has reached an inherent architectural ceiling at roughly 58k HTTP RPS. It suggests that the system has reached a **specific serial dataplane ceiling** before the additional 8-vCPU worker capacity can be exploited.

The strongest candidate is the intentional one-housekeeping-CPU design interacting with virtio/IRQ/softirq processing, but the hot generator fleet means that must still be proven. The right engineering response is therefore a synchronized packet-path investigation, not more flavor inflation.

The most promising opportunities are, in order:

1. remove generator limitations;
2. prove what consumes vCPU0;
3. verify multiqueue is both exposed and active;
4. measure per-queue IRQ/softirq concentration;
5. test a two-housekeeping-CPU image if CPU0 is the confirmed limiter;
6. test controlled queue steering as an alternative;
7. A/B HAProxy 2.8 listener sharding for CPS-heavy workloads;
8. disable connection logging as a measured product/operations tradeoff;
9. characterize TLS separately, including the Noble/OpenSSL 3 stack;
10. validate NUMA/NIC/QEMU/vhost locality on premium hosts;
11. only then use multi-Amphora correlated-load campaigns to set Standard ratio 4/5/6 and Pro/Elite isolation policy.

This sequence keeps the work focused on improving the existing Amphora offering while preserving the commercial objective: predictable customer performance with enough safe density to make a dedicated Octavia cluster economically efficient.

---

# Sources

[^1]: Internal engineering artifact, `OCTAVIA_HTTP_MAX_RPS_FINDINGS_AND_NEXT_RUN.md`, September 11, 2026. Current Pro/Elite max-RPS results, generator CPU caveat, per-vCPU and packet-rate observations.

[^2]: OpenStack Octavia, “2023.1 Series Release Notes,” CPU-pinning element and Amphora worker pinning. https://docs.openstack.org/releasenotes/octavia/2023.1.html

[^3]: OpenStack Nova, “Networking with neutron - virtio-net Multiqueue.” https://docs.openstack.org/nova/latest/admin/networking.html

[^4]: HAProxy Technologies, “Announcing HAProxy 2.8,” May 31, 2023. Listener sharding and `tune.listener.default-shards`. https://www.haproxy.com/blog/announcing-haproxy-2-8

[^5]: OpenStack Octavia, 2025.1 release/image documentation; Noble became the default Ubuntu Amphora base. See also OpenDev change “Update diskimage-create.sh to use noble as default.” https://opendev.org/openstack/octavia/commit/57eb9b49dbc6b87f46e615f07220f048be66e31b

[^6]: Ubuntu Packages, “haproxy in noble/noble-updates,” HAProxy 2.8.16 and `libssl3` dependency. https://packages.ubuntu.com/noble/net/haproxy and https://packages.ubuntu.com/en/noble-updates/haproxy

[^7]: HAProxy Technologies, “The state of SSL stacks,” May 6, 2025. https://www.haproxy.com/blog/state-of-ssl-stacks

[^8]: DigitalOcean Documentation, “How to Scale Regional Load Balancers,” last verified July 13, 2026. https://docs.digitalocean.com/products/networking/load-balancers/how-to/scale/

[^9]: OpenStack Octavia, “Set some amphora driver optimizations,” HAProxy TCP splicing and safe backend HTTP reuse. https://opendev.org/openstack/octavia/commit/53772f5320f964e98dba3d54ac645bf8075637d1

[^10]: DigitalOcean Documentation, “How to Manage Regional Load Balancers - Backend Keep-Alive,” last verified September 3, 2026. https://docs.digitalocean.com/products/networking/load-balancers/how-to/manage/

[^11]: HAProxy Technologies, “Performance tuning HAProxy Enterprise.” https://www.haproxy.com/documentation/haproxy-enterprise/administration/performance-tuning/

[^12]: Linux Kernel Documentation, “IP Sysctl.” https://docs.kernel.org/networking/ip-sysctl.html

[^13]: OpenStack Nova, “Networking with neutron - NUMA affinity.” https://docs.openstack.org/nova/latest/admin/networking.html

[^14]: Internal engineering artifact, `OCTAVIA_SERVICE_TIER_CAPACITY_DESIGN.md`, 2026. Shared/mixed/dedicated tier design, allocation-ratio and correlated-load methodology.

[^15]: Internal engineering artifact, `PRICING_RECOMMENDATION_1C4G.md`, August 26, 2026. Earlier 1-vCPU/4-GiB Amphora baseline and direct-nginx control.

[^16]: Linux Kernel Documentation, “Scaling in the Linux Networking Stack.” https://docs.kernel.org/networking/scaling.html

[^17]: HAProxy Technologies, “Multithreading in HAProxy.” https://www.haproxy.com/blog/multithreading-in-haproxy

[^18]: HAProxy Technologies, “How HAProxy Takes Advantage of Multi Core CPUs,” 2025. https://www.haproxy.com/blog/how-haproxy-takes-advantage-of-multi-core-cpus

[^19]: HAProxy Technologies, “Performance optimization for large systems,” listener shards/thread groups. https://www.haproxy.com/documentation/haproxy-configuration-tutorials/performance/performance-tuning/

[^20]: OpenStack Octavia 2025.1 Documentation, Amphora log offloading, Disable Local Log Storage and Disable Tenant Flow Logging. https://docs.openstack.org/octavia/2025.1/doc-octavia.pdf

[^21]: AMD, “Data Plane Development Kit Tuning Guide for AMD EPYC 7003 Series Processors,” NPS guidance. https://www.amd.com/content/dam/amd/en/documents/epyc-technical-docs/tuning-guides/data-plane-development-kit-tuning-guide-amd-epyc7003-series-processors.pdf

[^22]: Red Hat Enterprise Linux 8, “Optimizing virtual machine network performance,” `vhost_net` and virtio multiqueue. https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/8/html/configuring_and_managing_virtualization/optimizing-virtual-machine-performance-in-rhel_configuring-and-managing-virtualization

[^23]: OpenStack Nova, CPU topology / extra specs documentation, `hw:emulator_threads_policy`, dedicated/shared CPU sets. https://docs.openstack.org/nova/latest/admin/cpu-topologies.html and https://docs.openstack.org/nova/latest/configuration/config.html

[^24]: Red Hat networking/performance documentation, Receive Side Scaling and IRQ distribution. See RHEL performance/network tuning documentation. https://docs.redhat.com/

[^25]: Linux Kernel Documentation, segmentation offloads; Red Hat network performance guidance on GRO/TSO/GSO. https://docs.kernel.org/networking/segmentation-offloads.html

[^26]: Linux Kernel Documentation, NAPI / busy polling. https://docs.kernel.org/networking/napi.html

[^27]: AMD, EPYC 7003 tuning guides, power/C-state/determinism tradeoffs. https://www.amd.com/en/developer/zen-software-studio/applications/spack/amd-epyc-tuning-guides.html

[^28]: Red Hat Enterprise Linux Performance Tuning / TuneD documentation, network-latency and network-throughput profiles. https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/monitoring_and_managing_system_status_and_performance/

[^29]: OpenStack Nova, CPU thread policy and flavor extra specs. https://docs.openstack.org/nova/latest/admin/cpu-topologies.html

[^30]: OpenStack Nova, huge pages and CPU/NUMA topology documentation. https://docs.openstack.org/nova/latest/admin/huge-pages.html

[^31]: HAProxy Configuration Manual, `maxconn` and file-descriptor behavior. https://www.haproxy.com/documentation/haproxy-configuration-manual/latest/

[^32]: DigitalOcean, “Introducing new DigitalOcean Load Balancers for higher-scale business applications,” December 8, 2020. https://www.digitalocean.com/blog/introducing-new-digitalocean-load-balancers-plans

[^33]: DigitalOcean, “Load Balancer: Scaling to 1,000,000+ Connections,” July 25, 2024. https://www.digitalocean.com/blog/load-balancer-scaling-to-1000000-connections

[^34]: HAProxy Technologies, “How LinkedIn modernized its massive traffic stack with HAProxy,” December 18, 2025, summarizing LinkedIn Traffic Infra's HAProxyConf presentation. https://www.haproxy.com/blog/how-linkedin-modernized-its-massive-traffic-stack-with-haproxy
