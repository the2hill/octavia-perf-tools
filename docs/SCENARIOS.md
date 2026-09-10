# Scenario Reference

This harness deliberately separates different load-balancer limits instead of trying to summarize Octavia performance with one number. A flavor can have excellent request throughput but a modest concurrent-connection ceiling, or high connection capacity but lower TLS handshake rate.

## Benchmark engines

Two engines share the same OpenStack generator fleet and result/manifest pipeline:

| Engine | Best for | Output |
|---|---|---|
| `locust` | RPS, response latency, payload throughput, request-per-new-connection/CPS-like tests | Locust CSV history, RPS/latency charts, payload estimates |
| `connection_capacity` | Maximum simultaneous established sockets/sessions | Per-level established/surviving counts, connection establishment latency/rate, capacity charts |

The scenario selects the engine. Do not compare results produced by different engines as if they measure the same limit.

## Core request-rate scenarios

### `http_1k_keepalive`

**Measures:** HTTP request throughput and latency with connection reuse.

**Datapath:** client HTTP -> Octavia HTTP listener -> HTTP pool -> nginx HTTP.

Use this as the primary control when comparing Octavia flavors. The 1 KiB payload minimizes bandwidth pressure and keeps the test focused on request processing.

### `tls_passthrough_1k_keepalive`

**Measures:** request rate with end-to-end TLS while Octavia proxies encrypted traffic rather than terminating TLS.

**Datapath:** client TLS -> Octavia HTTPS passthrough -> nginx TLS.

Compare with `http_1k_keepalive` to see the impact of carrying encrypted traffic without Octavia TLS termination. nginx, not Octavia, performs the TLS handshake.

### `tls_termination_1k_keepalive`

**Measures:** Octavia frontend TLS termination cost.

**Datapath:** client TLS -> Octavia `TERMINATED_HTTPS` + Barbican certificate -> HTTP pool -> nginx HTTP.

Compare with HTTP and passthrough to isolate the cost of TLS termination in the Octavia datapath.

### `tls_termination_reencrypt_1k_keepalive`

**Measures:** TLS termination plus TLS re-encryption to backend members.

**Datapath:** client TLS -> Octavia termination -> Octavia TLS to members -> nginx TLS.

The backend certificate is validated by Octavia against the benchmark CA stored temporarily in Barbican.

## Maximum sustainable RPS scenarios

These are saturation-search scenarios rather than fixed characterization staircases. They use a 1 KiB keepalive response so payload bandwidth is unlikely to be the first limit.

Available datapaths:

- `http_1k_max_rps`
- `tls_passthrough_1k_max_rps`
- `tls_termination_1k_max_rps`
- `tls_termination_reencrypt_1k_max_rps`

The adaptive Locust shape works as follows:

1. Start at `max_rps.start_users`.
2. Wait for the requested user count to settle.
3. If the generator fleet cannot reach the requested user count within `max_rps.user_reach_timeout_seconds`, record a generator-side reach failure and back off rather than hanging.
4. Measure a clean window for `max_rps.measure_seconds`.
5. A measured level passes only if request failures are at or below `max_rps.failure_threshold_percent` and measured p99 is at or below `max_rps.p99_max_ms` (set p99 to `0` to disable the latency gate).
6. Passing levels grow by `max_rps.growth_factor` until the first failure or `max_rps.max_users`.
7. After a failure, the search bisects the last passing/failing concurrency range until it reaches `max_rps.search_resolution_users` or `max_rps.max_search_steps`.

The report records `max_sustainable_rps`, the user concurrency that produced it, the best level's p99/failure percentage, and whether a failing upper bound was actually found. If `max_rps.max_users` passes, the result is explicitly a **lower bound**; increase generator capacity and/or `max_users` before calling it the Octavia ceiling.

Do not compare `peak_rps_history` from an ordinary staircase to `max_sustainable_rps` from an adaptive search as though they were the same statistic. The latter is based on a sustained measurement window and quality gates.

## New-connection / CPS-like scenarios

### `http_1k_connection_churn`

Each request asks for `Connection: close`. RPS is therefore an approximation of new TCP connections per second. It is useful for comparing connection setup pressure, but it is not a raw socket-capacity test.

### `tls_termination_1k_connection_churn`

The TLS-termination equivalent of the HTTP churn test. This puts repeated TCP and TLS setup work on Octavia. Use it to compare handshake/connection setup behavior between flavors.

## Concurrent-connection capacity scenarios

These use the `connection_capacity` engine. The configured levels are **global totals across every generator VM/process**.

### `http_connection_capacity_idle`

Opens the requested number of TCP connections and leaves them application-idle during the hold interval. At the end of the hold the harness sends a GET on each socket to confirm that it is still usable.

Use this to investigate frontend connection-state capacity with minimal ongoing application work.

### `http_connection_capacity_active`

Opens HTTP keepalive connections, verifies each with an initial request, and sends periodic requests throughout the hold interval.

Use this as the most useful general HTTP concurrent-connection ceiling because it keeps both frontend and backend-side proxy state exercised.

### `tls_passthrough_connection_capacity_active`

Holds active TLS sessions through an HTTPS passthrough listener. nginx performs TLS, while Octavia maintains the proxied connection state.

### `tls_termination_connection_capacity_idle`

Completes TLS handshakes at Octavia, then leaves the sessions application-idle for the hold interval before final verification.

This focuses on simultaneous frontend TLS-session/socket state. Because no HTTP request is sent during the hold interval, it should not be treated as a backend-connection capacity measurement.

### `tls_termination_connection_capacity_active`

Holds TLS sessions terminated by Octavia and periodically sends HTTP requests on every connection.

This is the preferred connection-capacity scenario when you want a realistic TLS termination ceiling rather than idle session state alone.

### `tls_termination_reencrypt_connection_capacity_active`

Holds active frontend TLS sessions while Octavia also uses TLS to the members. This exercises the most expensive supported TLS datapath in the default catalog.

## Maximum simultaneous-connection scenarios

The following active-connection profiles are intended to answer "how high can this generator fleet safely push before either Octavia fails or the client source tuple space becomes the limit?":

- `http_max_connections_active`
- `tls_passthrough_max_connections_active`
- `tls_termination_max_connections_active`
- `tls_termination_reencrypt_max_connections_active`

Unlike the standard `connection_capacity.levels`, max profiles use `connection_capacity.max_levels_per_worker`. Every per-worker level is multiplied by `vm.locust.worker_vms` to form the global target. With four default workers, the default final 55,000-per-worker step is 220,000 global simultaneous connections. With twelve workers, the same profile automatically ends at 660,000.

This scaling is intentional: each generator VM normally contributes one source IP, so its available ephemeral source ports are the practical client-side connection ceiling to one VIP:port tuple. If every max level passes, the report does **not** claim that Octavia's maximum equals the last level. It reports that Octavia sustained at least that many connections and that the generator source-port safety ceiling was reached. Add generator VMs or additional source IPs and repeat.

If a lower level fails, the normal contiguous-staircase rule still applies: the reported sustainable connection maximum is the last continuously passing level.

## Bandwidth scenarios

### `http_64k_keepalive`

64 KiB responses. Useful after the 1 KiB RPS case to identify where payload throughput begins to matter.

### `http_1m_keepalive`

1 MiB responses. This is intentionally bandwidth-oriented; NIC and network-path limits can become the dominant ceiling.

### `tls_termination_64k_keepalive`

64 KiB responses with Octavia TLS termination. Compare against the HTTP 64 KiB profile to quantify TLS cost at a more bandwidth-heavy operating point.

## Idle versus active connection capacity

The distinction matters:

- **Idle** means the frontend socket/session exists but does not carry application traffic during the hold interval. It is primarily a state/memory/timeout test.
- **Active** means every connection is initially proven and receives periodic requests. It exercises more of the complete frontend -> pool -> member path.

For published flavor comparisons, prefer active capacity and use idle capacity as a diagnostic companion.

## How a capacity level is judged

For each configured global level the distributed workers record:

- requested connections
- attempted opens
- successfully established connections
- establishment failures and failure classes
- establishment p50/p95/p99 latency
- connections still usable after the hold interval
- survival failures
- observed establishment rate during the ramp
- generator/backend CPU and network telemetry

A level is considered **sustainable** when both establishment failures and survival failures remain within `connection_capacity.failure_threshold_percent`.

If every configured level passes, the result is reported as a lower bound: for example, "demonstrated at least 100,000 sustainable connections." Increase the levels to discover the actual ceiling.

## Generator limits that can create false ceilings

### Ephemeral source ports

Every TCP connection is identified by a source/destination tuple. With one source IP connecting to one LB address/port, a generator can exhaust its ephemeral source-port range before Octavia is full.

The harness tunes `net.ipv4.ip_local_port_range` and validates the highest configured target against `connection_capacity.source_port_guard_per_worker`. By default it refuses a campaign requiring more than 55,000 simultaneous connections from one generator VM/IP.

**Preferred fix:** increase `vm.locust.worker_vms`. This adds source IPs and CPU at the same time.

Only set `allow_source_port_overcommit: true` if you deliberately provide additional usable source addresses or have otherwise verified the client tuple space.

### File descriptors

Every held socket consumes a descriptor. The generator role raises `fs.file-max`, the capacity command raises its `ulimit -n`, and the node manifest captures these values. Keep `connection_capacity.file_descriptor_limit` comfortably above the per-process target.

### CPU

TLS establishment can saturate a generator CPU. Capacity tests therefore use multiple asyncio processes per VM (`connection_capacity.processes_per_vm`, default 2). If generator CPU approaches the warning threshold, add generator VMs or increase their flavor before attributing the ceiling to Octavia.

### TIME_WAIT

Each capacity level is independent. The holder uses abortive closes by default after a level so client-side TIME_WAIT does not accumulate and poison the next level. This happens after the measurement/hold interval.

## Recommended comparison sets

### Basic Octavia flavor characterization

1. `http_1k_keepalive`
2. `tls_termination_1k_keepalive`
3. `http_connection_capacity_active`
4. `tls_termination_connection_capacity_active`
5. `http_1k_connection_churn`
6. `tls_termination_1k_connection_churn`
7. `http_1m_keepalive`

This gives you RPS, TLS RPS, HTTP/TLS simultaneous connection capacity, approximate CPS, TLS handshake/setup pressure, and bandwidth. For explicit ceiling discovery, add `http_1k_max_rps`, `tls_termination_1k_max_rps`, `http_max_connections_active`, and `tls_termination_max_connections_active` as a separate saturation campaign rather than replacing the fixed characterization runs.

### TLS implementation characterization

1. `tls_passthrough_1k_keepalive`
2. `tls_termination_1k_keepalive`
3. `tls_termination_reencrypt_1k_keepalive`
4. `tls_passthrough_connection_capacity_active`
5. `tls_termination_connection_capacity_active`
6. `tls_termination_reencrypt_connection_capacity_active`

### Network-path characterization

Run the same scenario twice without changing anything except:

```yaml
benchmark:
  traffic_path: tenant_vip

generator_network:
  mode: auto
```

and:

```yaml
benchmark:
  traffic_path: floating_ip

generator_network:
  mode: auto
```

The first resolves to shared tenant-network generators; the second resolves to a dedicated externally routed generator network. Keep these as separate comparison populations.

## Persistent-LB scenario lifecycle

The canonical baseline suite keeps one LB/amphora for the selected Octavia flavor across all scenarios and repetitions. Scenario transitions do not reuse incompatible listener state: before each Octavia run the harness creates the listener, pool, members, health monitor, TLS secrets, and tuning required by that scenario, then removes those child resources after the run. The LB/VIP and Amphora VM remain in place until the Octavia phase ends.

This means HTTP, TCP/TLS passthrough, terminated HTTPS, re-encryption, normal request-rate tests, and connection-capacity tests can share the same Amphora while still receiving their own protocol-specific listener/pool configuration and listener connection limit.

## Listener connection limit and inactivity timeouts

Connection-capacity tests must not be constrained by listener policy before the flavor itself is stressed. The example configuration therefore sets:

```yaml
octavia:
  listener:
    connection_limit: 1000000
    timeout_client_data_ms: 300000
    timeout_member_data_ms: 300000
```

The harness applies these settings to every benchmark listener and records the values returned by Octavia in the target state/run manifest.

`connection_limit` must be at least the highest configured capacity level. The client inactivity timeout must be longer than the idle hold interval. The validator rejects configurations that would make those policy settings the obvious measured ceiling.

These values are benchmark controls, not recommended production defaults. If a provider rejects them, reduce them only with a corresponding reduction in the test levels/hold duration and document that constraint in the campaign metadata.

