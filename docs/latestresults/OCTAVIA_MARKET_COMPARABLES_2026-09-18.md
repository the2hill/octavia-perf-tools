# Octavia Amphora Market Comparables and Pricing Position — September 2026

**Status:** Updated after September 18, 2026 full-flavor / multi-scenario campaign
**Benchmark date:** 2026-09-18 UTC
**Scope:** Rackspace Amphora/HAProxy service positioning, public cloud comparables, price/capacity signals, and measured scenario envelopes
**Important:** This is a market-positioning document, not a final price book or performance SLA. This revision uses the supplied September 18 `comparison-summary.csv`, `selected-runs.csv`, the rebuild/run script, and the Elite 500->4000-user Locust history. The rebuild campaign itself exercised four core 1-KiB keepalive scenarios across the flavor matrix plus one separate Elite-only HTTP concurrency staircase. CPS/churn, simultaneous-connection, and dedicated 64-KiB/1-MiB bandwidth scenarios were **not part of this rebuild campaign**, so this revision does not invent current-MQ values for them. Floating-IP path, host-density, and HA/failover evidence remain separate product-validation workstreams.

---

# 1. Executive update

The September 18 campaign materially strengthens the case for differentiated Amphora flavors. The new data should **not** be reduced to a single RPS number: the workload shape changes the useful capacity substantially.

## Current measured HTTP/TLS scenario envelope

The normal staircase reports `median_peak_rps` / `peak_rps_history`; it is **not** the same statistic as adaptive `max_sustainable_rps`. The Elite HTTP results need to be split by workload fingerprint: the standard flavor-matrix suite (`suite_id=20260918T052148584530Z`, fingerprint `e7d6d69cf590adfc`) has three homogeneous runs at **89,687.7 / 93,180.9 / 94,680.4 RPS**, giving a clean median of **93,180.9 RPS**. The later Elite-only 500->4000-user diagnostic (`suite_id=20260918T150526815939Z`, fingerprint `36c2a02206267288`) peaked at **126,722.8 RPS** and is analyzed separately below. The unfiltered 4-run `comparison-summary.csv` median of 93,930.65 RPS mixes those two populations and should not be used as the normal Elite matrix reference.

| Scenario | Lite | Plus | Pro | Elite | Elite/Pro | Elite p99 | Elite payload | Elite quality note |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| HTTP 1-KiB keepalive | 13,470 RPS | 16,112 RPS | 57,309 RPS | **93,181 RPS** | **1.63x** | 130 ms | 0.763 Gbit/s | Homogeneous 3-run standard-matrix population; 0 failures and no validity/bottleneck warnings. |
| TLS passthrough 1-KiB keepalive | 25,930 RPS | 23,221 RPS | 72,766 RPS | **140,975 RPS** | **1.94x** | 98 ms | 1.155 Gbit/s | 0 total failures, but **2 of 3 Elite runs carried resource warnings**; treat 141k as an observed peak class, not yet a clean publishable ceiling. |
| TLS termination 1-KiB keepalive | 9,920 RPS | 12,248 RPS | 40,779 RPS | **73,892 RPS** | **1.81x** | 160 ms | 0.605 Gbit/s | 0 Elite failures and 0 resource-warning runs. |
| TLS termination + backend re-encryption | 10,330 RPS | 14,323 RPS | 47,634 RPS | **64,592 RPS** | **1.36x** | 180 ms | 0.529 Gbit/s | Elite recorded 3,892 total failures across 3 runs; lower tiers recorded millions of failures, so their peak-RPS values are not quality-gated capacity points. |

These scenario-specific values are more appropriate for product sizing than a single global “Elite RPS” claim. In the homogeneous standard-matrix populations, Elite is ~**1.63x** Pro for plain HTTP, ~1.94x for TLS passthrough, ~1.81x for TLS termination, and ~1.36x for re-encryption. The separate Elite concurrency diagnostic reaches a higher plain-HTTP peak, but it uses a different workload fingerprint and must remain a separate evidence point.

The latest summary also makes an important methodological distinction: **zero failures does not automatically mean a run is unconstrained**. Elite TLS passthrough has zero aggregate failures but resource warnings in 2/3 runs, so the 140,975-RPS median should not be promoted as a clean service ceiling until those warnings are identified and either eliminated or shown to be irrelevant.

## Adaptive max-RPS reference remains important

The separate clean Elite `http_1k_max_rps` campaign remains a key datapoint: median sustainable RPS was approximately **127,756 RPS** across three runs, with 6 ms best p99, 0% failures, and no generator warnings. That is an adaptive-search result and should remain separate from the normal staircase `peak_rps_history` numbers above.

A separate ~137,126 RPS Elite adaptive run is still classified as generator-hot because all eight prior generator nodes reached 100% CPU. It is evidence of additional dataplane headroom, but not the clean primary ceiling.

## What changed commercially

The old pre-MQ picture suggested that Pro and Elite were close to the same throughput. The September results invalidate that conclusion for the current multiqueue configuration. Elite now demonstrates a materially larger measured envelope across every core scenario, with the largest separation in TLS passthrough.

This also changes how pricing should be discussed: **capacity needs to be tied to workload class**. A customer buying Elite for 1-KiB plain HTTP gets a different measured capacity envelope than one using TLS passthrough or full TLS termination/re-encryption.

---

# 2. DigitalOcean: the cleanest fixed $/RPS comparator

DigitalOcean currently prices Regional HTTP Load Balancers at **$12/month per node**. Each node adds a documented maximum of:

- **10,000 requests/sec**;
- **10,000 simultaneous connections**;
- **250 new SSL connections/sec** with ordinary certificates;
- **50 new SSL connections/sec** with RSA-4096 certificates.

Customers can scale to as many as 200 nodes subject to account limits.

This is the most useful public fixed-price comparator because the customer explicitly buys another capacity node and receives another published RPS/connection allowance.

## 2.1 DigitalOcean node-equivalent comparison

Using only the published 10k HTTP RPS/node maximum and rounding up to whole nodes:

| Rackspace benchmark point | Measured HTTP RPS | DO 10k-RPS nodes needed | DO node price | Approx. DO monthly capacity price |
|---|---:|---:|---:|---:|
| Pro MQ median | ~60,264 | 7 | $12 | **$84/mo** |
| Pro latest single run | ~62,711 | 7 | $12 | **$84/mo** |
| Elite MQ median | ~127,756 | 13 | $12 | **$156/mo** |

This is not an SLA equivalence. DigitalOcean's number is a documented product maximum, while the Rackspace number is a measured reference workload. Protocol features, payload, HA architecture, path, and enforcement semantics differ. But it is a very useful market-sizing signal.

### Interpretation

At the clean adaptive Elite HTTP result, one active Amphora is delivering roughly the HTTP request-rate class that DigitalOcean exposes through **13 capacity nodes**. The homogeneous normal-matrix HTTP median is **~93.2k RPS** (roughly a 10-node class), while the separate concurrency diagnostic peaks at **~126.7k RPS** (roughly a 13-node class). This spread is exactly why the measurement method and workload fingerprint must accompany any market comparison.

That does not automatically mean Elite should cost $156/month. It means that a single-active Elite list price in roughly the low-to-mid hundreds per month can be justified in market terms if the remaining CPS, simultaneous-connection, dedicated-bandwidth, density, and HA evidence supports the same tier separation.

## 2.2 DigitalOcean's older vertical proxy benchmark

DigitalOcean's 2020 managed-LB benchmark used a synthetic **HTTPS** workload and reported approximately:

- 1-vCPU Small: **8.3k RPS**;
- 2-vCPU Medium: **23.9k RPS**;
- 4-vCPU Large: **41.9k RPS**.

Those old absolute numbers should not be compared directly with the current Rackspace HTTP benchmark because HTTPS termination is materially more expensive than plain HTTP. The scaling behavior is still useful historically: managed software proxy instances can make strong use of additional CPU when the dataplane is not serialized.

The new Rackspace MQ result now tells the same qualitative story. The prior flat 4-vCPU/8-vCPU curve was not evidence that HAProxy itself could not vertically scale; it was evidence that the guest network path was misconfigured for vertical scale.

---

# 3. Scaleway: useful bandwidth and connection-tier comparator

Scaleway currently exposes four managed LB sizes with explicit bandwidth and simultaneous-connection limits:

| Scaleway size | Bandwidth | Max simultaneous connections | Current hourly price (PAR-1) | 730-hour equivalent |
|---|---:|---:|---:|---:|
| LB-S | 200 Mbps | 20,000 | €0.023/h | **€16.79/mo** |
| LB-GP-M | 500 Mbps | 50,000 | €0.054/h | **€39.42/mo** |
| LB-GP-L | 1 Gbps | 160,000 | €0.094/h | **€68.62/mo** |
| LB-GP-XL | 4 Gbps | 3,000,000 | €0.941/h | **€686.93/mo** |

Scaleway explicitly notes that these are performance limits by size and that application behavior can encounter other limits before the headline bandwidth number.

## 3.1 Mapping the 1-KiB Rackspace workload to payload bandwidth

Payload-only throughput for the current HTTP benchmark is approximately:

| Rackspace result | HTTP RPS | 1-KiB response payload rate |
|---|---:|---:|
| Pro MQ median | ~60,264 | **~0.494 Gbit/s** |
| Elite MQ median | ~127,756 | **~1.047 Gbit/s** |

This excludes HTTP/TCP/IP/Ethernet overhead and request bytes, so actual wire throughput is higher.

Directional comparison:

- Pro lands almost exactly in the payload-throughput class of Scaleway's **500-Mbps LB-GP-M**.
- Elite's response payload alone is already slightly above **1 Gbps**, so a strict bandwidth-sizing exercise would push beyond LB-GP-L and toward the 4-Gbps class.

Do not interpret that as “Elite equals an LB-GP-XL.” Scaleway's product is a managed HA service with a different dataplane and published concurrency limits. The useful point is that Elite is no longer a small-proxy performance class: even the simple 1-KiB test is producing approximately a gigabit/second of application payload.

---

# 4. Akamai/Linode NodeBalancer: low fixed entry price, sparse RPS disclosure

Akamai/Linode currently prices standard NodeBalancers starting at **$10/month ($0.015/hour)**. Premium pricing is contact-sales.

Published connection limits include:

- non-premium: **10,000 concurrent connections**;
- premium: **100,000 concurrent connections**.

The product supports L4/L7 behaviors, but Akamai does not publish a useful standard RPS envelope comparable with DigitalOcean's 10k RPS/node unit.

This makes NodeBalancer primarily a **price and concurrency anchor**, not a clean RPS comparator.

Commercial lesson: the market supports very inexpensive entry LBs, but premium consistency/capacity can be packaged separately. That remains compatible with a Rackspace Standard/shared vs Pro/Elite isolation ladder.

---

# 5. Vultr: another $10 managed-LB floor

Vultr states that Load Balancers start at **$10/month per instance**, with pricing varying by region. The product supports L4 and L7, SSL termination, health checks, sticky sessions, and backend autoscaling behavior.

Vultr also states that the LB itself is bandwidth-neutral for billing; traffic charges are applied to attached instances rather than as a separate LB bandwidth meter.

Vultr does not publish a useful per-instance RPS ceiling in its current public documentation, so the $10 price is an entry-price signal only.

This reinforces an important distinction for Rackspace pricing:

> A $10-$12 managed-LB entry price exists in the market, but those prices do not imply that a high-capacity, compute-backed premium tier should also be $10-$12.

---

# 6. Hetzner: connection-size ladder with deliberately limited public performance promises

Hetzner publicly documents the following primary load-balancer performance sizing signal:

- LB11: up to **10,000 concurrent connections**;
- LB21: up to **20,000 concurrent connections**;
- LB31: up to **40,000 concurrent connections**.

Hetzner states that larger plans receive more CPU and memory, but does not publish a fixed RPS guarantee or fixed new-connection rate. It also states that bandwidth is not explicitly limited; LBs scheduled on the same node share a **2x10-Gbit** hardware interface.

This is strategically relevant because Hetzner openly acknowledges shared-host/network reality rather than pretending a VM-sized LB has an unlimited dataplane.

For Rackspace, that supports publishing a measured capacity envelope while keeping some dimensions explicitly best-effort unless the scheduler/host design can guarantee them.

---

# 7. AWS ALB: sustained 1-KiB traffic is expensive under LCU billing

AWS Application Load Balancer pricing in US-East currently includes:

- **$0.0225/hour** per ALB;
- **$0.008 per LCU-hour**.

An ALB LCU is based on the highest of several dimensions, including new connections, active connections, processed bytes, and rule evaluations. For EC2/container/IP targets, **1 LCU includes 1 GB/hour of processed bytes**.

For the current keepalive-heavy 1-KiB Rackspace benchmark, the byte dimension is a useful lower-bound cost illustration.

## 7.1 Payload-only lower-bound model

Using only the 1-KiB response payload and ignoring request bytes, headers, protocol overhead, internet egress, and any additional rule cost:

### Pro MQ median

- ~60,264 RPS
- ~222.16 GB/hour of response payload
- ~222.16 byte-dimension LCUs/hour
- normalized 730-hour cost: approximately **$1,314/month**

### Elite MQ median

- ~127,756 RPS
- ~470.96 GB/hour of response payload
- ~470.96 byte-dimension LCUs/hour
- normalized 730-hour cost: approximately **$2,767/month**

These are intentionally lower bounds. AWS counts processed traffic according to its ELB billing rules, and a real customer workload includes request bytes, response headers, TCP/TLS overhead, possibly more rules, and internet data transfer.

### Commercial implication

The important contrast is **billing model, not a claim that the two products are architecturally equivalent**. AWS ALB automatically scales and charges for usage; Rackspace's proposed Amphora tiers buy a fixed amount of measured capacity for a fixed monthly price.

Using the current provisional Rackspace single-active bands:

| Comparison | Rackspace flat-price target | AWS ALB payload-only lower bound if driven at the Rackspace benchmark rate for 730h | Approx. monthly-average benchmark utilization where AWS payload cost reaches the Rackspace price | Practical meaning |
|---|---:|---:|---:|---|
| Pro MQ (~60.3k RPS) | **$65-$90/mo** | **~$1,314/mo** | **~5.0-6.8%** | If traffic is bursty and averages only a few percent of the Pro ceiling, ALB's usage model may be cheaper. If a customer drives several-thousand RPS continuously, the fixed Pro price can become much more predictable and economical. |
| Elite MQ (~127.8k RPS) | **$125-$165/mo** | **~$2,767/mo** | **~4.5-6.0%** | The same effect is stronger at Elite scale: AWS avoids pre-purchasing 128k-RPS capacity, but sustained utilization turns the LCU byte dimension into a large recurring charge. |

Those break-even percentages correspond roughly to **~3.0k-4.1k average RPS for Pro** and **~5.8k-7.6k average RPS for Elite**, assuming the same 1-KiB response workload and that the byte dimension remains the dominant AWS LCU dimension. This is a sizing illustration, not an AWS quote for every workload.

So the commercial distinction is:

- **AWS ALB:** low fixed entry cost, elastic/autoscaled capacity, variable bill tied to actual traffic dimensions; attractive for low-duty-cycle or highly bursty services.
- **Rackspace Pro/Elite:** higher fixed base price, explicit pre-sized capacity, no LCU meter; potentially attractive for sustained workloads that make consistent use of the purchased capacity.
- normal network/egress charges remain separate in either model and must be compared independently.

---

# 8. Google Cloud: byte pricing plus explicit proxy capacity engineering

Google Cloud Load Balancing pricing currently lists:

- first five forwarding rules: **$0.025/hour**;
- many US regional load-balancing paths: **$0.008/GiB inbound** and **$0.008/GiB outbound** processed by the load balancer.

Google also publishes unusually useful internal capacity signals for Envoy-based regional proxy fleets. One proxy can generally handle up to:

- **18 MB/sec**;
- **600 HTTP** or **150 HTTPS new connections/sec**;
- **3,000 active connections**;
- **1,400 RPS** with Cloud Logging disabled.

Google explicitly states that 100% request logging can reduce the per-proxy RPS figure from **1,400 to about 700**.

That observability/performance tradeoff is directly relevant to Amphora engineering and validates continuing to benchmark HAProxy connection logging separately.

## 8.1 Payload-only GCP cost illustration

Using the documented US regional $0.008/GiB processing rate, one forwarding-rule charge, and **only the 1-KiB response payload**:

| Rackspace benchmark point | Response payload | Approx. GCP LB processing + forwarding-rule lower bound, 730h |
|---|---:|---:|
| Pro MQ median | ~206.9 GiB/h | **~$1,227/mo** |
| Elite MQ median | ~438.6 GiB/h | **~$2,580/mo** |

Again, this is not a quote for every GCP LB architecture. Global vs regional products, traffic direction, internet egress, proxy charges, and optional features differ. It is a simple demonstration that byte-metered managed LBs can become expensive under sustained small-response traffic even though they are attractive for elastic workloads.

## 8.2 Capacity comparison, not product equivalence

If the RPS dimension alone dominated a Google Envoy regional proxy fleet, ~127.8k RPS would correspond to roughly **92 proxy instances at 1,400 RPS/proxy** with logging disabled. That is an internal autoscaling unit, not something customers buy directly, but it illustrates how hyperscalers horizontally decompose a workload that a single tuned Elite Amphora is currently handling in one active VM.

---

# 9. Azure Application Gateway v2: multi-dimensional capacity unit model

Azure Application Gateway v2 does not present a simple public $/RPS unit. Its billing and scaling model is capacity-based.

Microsoft currently documents one Capacity Unit as the maximum of:

- **2,500 persistent connections**;
- **1 GB/hour / 2.22 Mbps throughput**;
- **1 Compute Unit**.

For Standard_v2, Microsoft states that each instance can handle approximately:

- **25,000 persistent connections**;
- **500 Mbps throughput**;
- **10 compute units**.

Microsoft also documents approximately **50 TLS connections/sec per compute unit** for RSA-2048 and a deployment-level maximum of 62,500 connections/sec for Standard_v2.

The useful product lesson is not a direct price comparison. It is that Azure also exposes a multi-dimensional capacity model rather than pretending one RPS number fully describes a load balancer.

That supports a Rackspace product envelope containing at least:

- HTTP RPS;
- HTTPS termination RPS;
- new TCP connections/sec;
- new TLS connections/sec;
- simultaneous connections;
- throughput;
- latency at the reference point.

---

# 10. Rackspace Spot: important internal portfolio anchor

Rackspace Spot currently lists managed Kubernetes Load Balancers at **$10/month** with simple fixed pricing. Public Spot documentation does not provide an RPS or connection-capacity envelope that can be compared with Amphora.

Therefore Spot should be treated as:

- an internal **entry-price anchor**;
- evidence that simple fixed pricing is already part of the Rackspace portfolio;
- **not** evidence that a high-capacity Octavia Pro/Elite tier should cost $10/month.

The new Amphora service can justify a separate price ladder if it exposes richer OpenStack-native L7/TLS capabilities and a measured capacity envelope.

---

# 11. Updated comparative matrix

| Provider/product | Public price/capacity model | What a Rackspace-sized workload maps to | Practical contrast vs proposed Rackspace Pro/Elite |
|---|---|---|---|
| DigitalOcean Regional HTTP LB | **$12/mo/node**; each node adds up to 10k RPS, 10k connections and 250 normal TLS CPS | Pro ~= **7 nodes / $84/mo** by published RPS; Elite ~= **13 nodes / $156/mo** | Closest fixed-capacity comparison. Those prices land almost exactly inside the provisional Rackspace Pro/Elite bands, making DO the strongest simple market anchor. |
| Scaleway LB-S/M/L/XL | Fixed hourly size ladder: 200 Mbps / 500 Mbps / 1 Gbps / 4 Gbps plus published connection limits | Pro's 1-KiB response payload is ~0.49 Gbps; Elite is ~1.05 Gbps before protocol overhead | Useful bandwidth-class comparison, **not RPS-equivalent**. Pro is around the 500-Mbps class; Elite already exceeds a 1-Gbps payload-only class, so real wire rate requires more headroom. |
| Akamai/Linode NodeBalancer | **$10/mo Basic**; Premium is sales-priced; 10k vs 100k concurrent-connection signal | No public RPS figure lets us translate 60k/128k Rackspace RPS into a NodeBalancer count | Useful entry-price and concurrency anchor only. It should not be used to argue that Pro/Elite are expensive or cheap on RPS. |
| Vultr Load Balancer | Starts around **$10/mo**; horizontal sizing available, but no useful public per-node RPS envelope | No defensible Pro/Elite RPS equivalence | Entry-price anchor only. Rackspace's premium has to be justified by measured capacity/features, not by comparing the $10 sticker price alone. |
| Hetzner LB11/LB21/LB31 | Fixed plans with 10k/20k/40k connection limits; larger plans receive more CPU/RAM; host NIC is shared | No published RPS value supports a Pro/Elite conversion | Supports the idea of explicit size tiers and honest shared-infrastructure caveats, but not a $/RPS comparison. |
| AWS ALB | **$0.0225/h + $0.008/LCU-h**; automatically scales; the highest usage dimension drives LCU billing; 1 GB/h processed bytes = 1 LCU for EC2/IP targets | At 100% sustained benchmark load, **Pro ~= $1.3k/mo** and **Elite ~= $2.8k/mo** from response-payload LCUs alone. Against proposed Rackspace bands, byte-cost break-even occurs at only **~5-7% average benchmark utilization** | AWS is potentially cheaper for low-duty-cycle/bursty traffic because customers do not pre-buy a 60k/128k capacity tier. Rackspace becomes economically attractive for sustained traffic because the LB price stays flat instead of scaling with processed bytes/LCUs. |
| Google Cloud LB | Forwarding-rule charge plus regional data-processing charges; Envoy capacity is engineered across RPS, bandwidth and connections | Payload-only sustained-load illustration is about **$1.2k/mo Pro / $2.6k/mo Elite** under the modeled regional rate | Same broad economic contrast as AWS: elastic/usage-based managed capacity vs Rackspace fixed capacity. Useful engineering comparator, but not an apples-to-apples RPS SKU. |
| Azure Application Gateway v2 | Fixed gateway charge plus capacity-unit billing across compute, persistent connections and throughput | No single RPS conversion is defensible because multiple capacity dimensions can dominate | Reinforces publishing a multi-dimensional Rackspace envelope. Rackspace's advantage would be simpler flat flavor pricing, not necessarily universally lower cost. |
| Rackspace Spot LB | **$10/mo** fixed entry price; no public RPS envelope | No performance-equivalent mapping to Pro/Elite | Internal proof that customers understand simple fixed LB pricing, but not a capacity comparator for a 60k/128k Amphora tier. |
| **Rackspace Octavia Pro MQ** | Proposed flat flavor; clean adaptive HTTP reference **~60.3k median sustainable RPS**; September normal-staircase peaks: HTTP **57.3k**, TLS passthrough **72.8k**, TLS termination **40.8k**, re-encryption **47.6k** | Market-positioning band currently **~$65-$90/mo** single-active | Best interpreted as a workload-specific capacity tier. DigitalOcean RPS-node math is most comparable to plain HTTP; TLS/CPS and connection dimensions need separate sizing. |
| **Rackspace Octavia Elite MQ** | Proposed flat flavor; clean adaptive HTTP reference **~127.8k median sustainable RPS**; September standard matrix: HTTP **93.2k**, TLS passthrough **141.0k**, TLS termination **73.9k**, re-encryption **64.6k**; separate HTTP concurrency diagnostic peaked at **126.7k** | Market-positioning band currently **~$125-$165/mo** single-active | Strongest differentiated tier. Keep the one-off concurrency staircase separate from the normal matrix; future price/product claims should use per-scenario envelopes rather than one universal RPS number. |

---

# 12. Provisional price-positioning implications

These are **market test bands**, not final recommended list prices. They do not include Rackspace's exact compute cost, host-density economics, support margin, control-plane overhead, HA topology cost, or expected utilization.

## 12.1 What the market anchors suggest

The clearest fixed-capacity comparison is DigitalOcean:

- Pro RPS class: ~7 DO nodes => **$84/month**.
- Elite RPS class: ~13 DO nodes => **$156/month**.

The cheapest managed-LB products from Akamai/Vultr/Rackspace Spot cluster around **$10/month**, but they do not disclose anything close to the current Elite RPS envelope.

Scaleway provides another useful anchor:

- ~500-Mbps managed LB: ~€39/month;
- 1-Gbps managed LB: ~€69/month;
- 4-Gbps managed LB: ~€687/month.

The hyperscaler byte-metered examples show that sustained usage at the current Rackspace RPS can cost well into four figures per month before normal internet egress.

## 12.2 Reasonable provisional single-active price bands

If Rackspace wants simple flat capacity-flavor pricing and intends to be attractive versus DigitalOcean's fixed node model, a defensible *market-positioning* range is approximately:

| Tier | Current clean HTTP reference | Provisional single-active list-price band | 730h equivalent hourly band |
|---|---:|---:|---:|
| Standard / 1-vCPU | previous ~8-11k RPS class | **~$22-$30/mo** | ~$0.030-$0.041/h |
| Pro / 4-vCPU MQ | ~60k RPS | **~$65-$90/mo** | ~$0.089-$0.123/h |
| Elite / 8-vCPU MQ | ~128k RPS | **~$125-$165/mo** | ~$0.171-$0.226/h |

Why these bands are interesting:

- Pro can sit below or near DigitalOcean's ~$84/month equivalent 7-node RPS capacity.
- Elite can sit below or near DigitalOcean's ~$156/month equivalent 13-node RPS capacity.
- Both remain dramatically simpler than LCU/GiB capacity billing.
- The price ladder roughly preserves increasing revenue with allocated compute while still rewarding vertical efficiency.

These should **not** become final list prices until internal cost/density is overlaid.

## 12.3 HA should be priced separately from capacity

Stock Amphora ACTIVE_STANDBY provides resilience, not 2x active throughput. Therefore do not advertise two Amphorae as two throughput units.

The clean product model remains:

```text
capacity flavor = Standard / Pro / Elite active dataplane envelope
HA topology     = single vs active/standby resilience option
```

If the standby consumes a full equivalent VM reservation, the HA price has a real resource cost and may need to approach another capacity instance economically. If host scheduling lets standby capacity be managed differently, a smaller HA uplift might be viable. This needs cost modeling rather than a marketing guess.

---

# 13. What the new results change about product strategy

The September 18 campaign shows that the same Amphora flavor can have very different useful capacity depending on dataplane mode. In the homogeneous standard-matrix populations, the largest Elite/Pro separation is TLS passthrough (~1.94x), followed by TLS termination (~1.81x), plain HTTP (~1.63x), and full re-encryption (~1.36x).

The product matrix should therefore avoid a single undifferentiated “RPS” promise. The useful customer-facing model is a workload-specific reference envelope:

```text
HTTP/L7 keepalive       -> reference RPS + latency/failure gate
TLS passthrough         -> reference RPS + connection/CPS evidence
TLS termination         -> reference RPS + full-handshake CPS
TLS re-encryption       -> reference RPS + backend-TLS behavior
connection churn        -> new connection/sec + p99
active connections      -> simultaneous connection envelope
bandwidth workloads     -> payload Gbit/s + packet-rate envelope
```

The DigitalOcean 10k-RPS/node number is strongest as a plain-HTTP sizing anchor. Its SSL-CPS and connection limits should be compared only with the corresponding Rackspace CPS/connection tests, not with keepalive RPS.

## 13.1 Elite is now a real product, not just a larger VM

Before MQ, Elite's ~58k RPS made it difficult to justify a large premium over Pro. The clean adaptive HTTP result changes that materially:

- Pro: ~60.3k median sustainable HTTP RPS in the clean adaptive reference;
- Elite: ~127.8k median sustainable HTTP RPS in the clean adaptive reference, ~2.12x Pro;
- the homogeneous September HTTP matrix reports ~57.3k Pro and **~93.2k Elite** (three standard-fingerprint runs); the separate 500->4000-user Elite diagnostic peaked at ~126.7k and is not part of that matrix median;
- TLS request-rate scaling is scenario dependent rather than universally 2x.

That supports a differentiated Elite tier, but it also means the service should publish the workload and measurement method beside any capacity number.

## 13.2 Vertical scaling is currently economically credible

The clean adaptive 4->8 vCPU result is ~2.12x sustainable HTTP RPS for 2x guest vCPU. The homogeneous September normal-staircase HTTP population gives **~1.63x** Pro->Elite scaling. TLS passthrough and termination scale even more strongly in the same matrix (~1.94x and ~1.81x), while re-encryption scales less strongly (~1.36x).

The next architectural breakpoint is therefore not “does 8 vCPU help?” but:

> At what flavor size does vertical scaling stop being cheaper than horizontal active-active architecture?

That still needs 16-vCPU experiments, host NUMA/locality testing, and potentially a multi-active architecture study.

## 13.3 MQ should be treated as a product prerequisite

The competitive conclusion depends on a correctly configured dataplane. The old single-queue Elite result would have materially underpriced or over-resourced the product if used for commercial sizing.

Virtio MQ exposure, active queue count, and observed queue/IRQ distribution should therefore become part of Amphora image/flavor acceptance testing rather than an optional tuning detail.

## 13.4 Publish a reference envelope, not only vCPU count

Most customers do not care that Elite has 8 vCPU. They care what it can do. The table below replaces the old `TBD`-heavy version with the measurements currently present in the September 18 comparison data.

### Current measured request-rate envelope

Each cell reports **median peak RPS / median p99 / median peak payload Gbit/s**. These are engineering observations, not unconditional SLA guarantees. For Elite HTTP, the table uses the three homogeneous standard-matrix runs (`e7d6d69cf590adfc`) rather than the unfiltered 4-run aggregate, which also contains the separate concurrency diagnostic.

| Scenario | Lite | Plus | Pro | Elite | Current quality signal |
|---|---:|---:|---:|---:|---|
| HTTP 1-KiB keepalive | **13.5k / 840 ms / 0.110 Gb/s** | **16.1k / 670 ms / 0.132** | **57.3k / 220 ms / 0.469** | **93.2k / 130 ms / 0.763** | Homogeneous 3-run Elite matrix population; 0 failures, 0 validity warnings, 0 bottleneck warnings. |
| TLS passthrough 1-KiB | **25.9k / 450 ms / 0.212 Gb/s** | **23.2k / 460 ms / 0.190** | **72.8k / 170 ms / 0.596** | **141.0k / 98 ms / 1.155** | Lite: 21,472 total failures; Plus: 54,075; Pro/Elite: 0. **Elite has resource warnings in 2/3 runs.** |
| TLS termination 1-KiB | **9.9k / 1000 ms / 0.081 Gb/s** | **12.2k / 890 ms / 0.100** | **40.8k / 250 ms / 0.334** | **73.9k / 160 ms / 0.605** | Lite: 2,010 total failures; Plus: 667; Pro/Elite: 0. No resource-warning runs. |
| TLS termination + re-encryption | **10.3k / 10,000 ms / 0.085 Gb/s** | **14.3k / 10,000 ms / 0.117** | **47.6k / 320 ms / 0.390** | **64.6k / 180 ms / 0.529** | Lite: 3,039,021 failures; Plus: 4,077,378; Pro: 4,353,654; Elite: 3,892. No resource-warning runs, but lower-tier peaks clearly fail quality gating. |
| Clean adaptive HTTP sustainable RPS | current clean value not imported | current clean value not imported | **~60.3k**, 11 ms accepted p99, 0% failures | **~127.8k**, 6 ms accepted p99, 0% failures | Separate adaptive-search dataset; do not merge numerically with staircase peaks. |

The payload values above are the benchmark's `median_peak_payload_gbps` for the 1-KiB scenarios. They are useful observed payload rates for these request-rate tests, but they are **not substitutes for dedicated 64-KiB/1-MiB bandwidth-ceiling scenarios**.

The re-encryption row is especially important. The latest aggregate does not contain failure percentages or total-request denominators, so this revision intentionally reports **total failures** rather than carrying forward stale percentages from an older summary. Lite, Plus, and Pro clearly do not have quality-gated sellable capacity at those reported peak-RPS points. Elite is much cleaner, but its 3,892 failures still mean the 64.6k peak should be paired with an explicit failure/SLO gate before publication.

### Elite HTTP concurrency-saturation diagnostic (separate population)

The Elite-only run with fingerprint `36c2a02206267288` used six 60-second stages at 500, 750, 1000, 1500, 2000, and 4000 users. It is intentionally **not** another replicate of the standard flavor matrix. The table below uses the `Aggregated` rows from `locust_stats_history.csv`; RPS values are medians/peaks within each 60-second user stage, and latency values are medians/maxima of the Locust history p95/p99 columns observed during that stage.

| Users | Median RPS | Peak RPS | Median p95 | Median p99 | Max observed p99 | Failures |
|---:|---:|---:|---:|---:|---:|---:|
| 500 | **121,042.3** | 126,340.6 | 5 ms | 6 ms | 8 ms | 0 |
| 750 | **122,244.5** | **126,722.8** | 8 ms | 9 ms | 9 ms | 0 |
| 1,000 | **122,460.9** | 124,071.3 | 9 ms | 10 ms | 11 ms | 0 |
| 1,500 | **122,022.9** | 123,217.0 | 13 ms | 15 ms | 17 ms | 0 |
| 2,000 | **117,906.4** | 123,437.4 | 19 ms | 22 ms | 23 ms | 0 |
| 4,000 | **108,535.5** | 115,411.2 | 42 ms | 56 ms | 59 ms | 0 |

The saturation shape is more useful than the single 126.7k peak. Throughput is already essentially flat by 500-1000 users, remains around 122k through 1500 users, and then falls as concurrency rises further. Relative to the 1000-user median, the 2000-user stage is ~3.7% lower and the 4000-user stage ~11.4% lower, while median p99 rises from 10 ms to 22 ms and then 56 ms. This is strong evidence that additional offered concurrency beyond roughly 750-1500 users does not buy more throughput for this workload; it primarily consumes latency headroom.

The run completed **42,935,645 requests with zero failures**. Its whole-run summary reports 126,722.8 peak RPS and 41 ms p99, but the stage history is the better source for explaining where the curve flattens.

### Additional envelope dimensions not exercised in this rebuild campaign

The September 18 rebuild/run script executed the four 1-KiB core keepalive scenarios plus the Elite-only HTTP concurrency staircase. The following scenario families exist in the harness and may have historical/pre-MQ evidence, but **they were not part of this rebuild campaign**. They therefore remain open current-MQ product-envelope dimensions rather than `TBD` placeholders or assumed completed work.

| Dimension | Benchmark scenario family | Current documentation status |
|---|---|---|
| TCP/new-connection CPS-like rate | `http_1k_connection_churn` | **Not run in this rebuild campaign; current-MQ reference still required** |
| TLS full-handshake CPS-like rate | `tls_termination_1k_connection_churn` | **Not run in this rebuild campaign; current-MQ reference still required** |
| Simultaneous active connections | `*_connection_capacity_active`, `*_max_connections_active` | **Not run in this rebuild campaign; current-MQ reference still required** |
| Dedicated payload/bandwidth ceiling | `http_64k_keepalive`, `http_1m_keepalive`, `tls_termination_64k_keepalive` | **Not run in this rebuild campaign; current-MQ reference still required** |

Legacy/pre-MQ results should not populate the current commercial reference envelope because the multiqueue change materially altered dataplane scaling.

The word **reference** remains important. Before publishing a product limit, Rackspace still needs to define the workload fingerprint and the acceptable latency/failure gate. The normal-staircase peaks above are evidence; the clean adaptive HTTP points are closer to the form of a sellable capacity reference because they explicitly applied quality gates.

---

# 14. Evidence still to fold into final pricing

The core HTTP/TLS keepalive matrix is measured, and the Elite concurrency staircase now explains how the 8-vCPU tier behaves as offered concurrency rises. The remaining work is to **run** the missing current-MQ product-envelope dimensions and finish operational validation:

1. **Run current-MQ TCP connection-churn tests** and report new-connection/sec with p99/failure gates.
2. **Run current-MQ TLS connection-churn/full-handshake tests**; keep full handshakes distinct from resumed TLS sessions.
3. **Run active/max simultaneous-connection tests** and distinguish an observed ceiling from a generator/source-port lower bound.
4. **Run 64-KiB / 1-MiB bandwidth tests** and report both payload Gbit/s and packet rate; do not substitute the 1-KiB derived payload-rate calculation for a bandwidth test.
5. **Optionally run adaptive max-RPS searches for TLS passthrough, termination, and re-encryption** if those are intended to become quality-gated product reference numbers rather than normal-staircase observations.
6. **Floating-IP/public path performance** rather than only tenant-VIP.
7. **Connection logging on/off** impact.
8. **ACTIVE_STANDBY failover behavior under load**.
9. **Host-density/noisy-neighbor tests** for Lite/Plus/Pro economics.
10. **Dedicated PCPU / NUMA-local Elite validation** if Elite will carry a premium consistency claim.
11. **Multi-Amphora-per-host stress** to determine actual sellable host density and gross margin.

The TLS request-rate question is already partially answered: Elite measured ~73.9k RPS for frontend TLS termination and ~64.6k RPS for termination plus backend re-encryption in the normal staircase. The remaining TLS commercial unknown is principally **new TLS handshakes/sec, resumed-session behavior, and the quality-gated sustainable point**, not whether TLS termination was tested at all.

---

# 15. Current conclusion

The multiqueue data changes the competitive assessment in Rackspace's favor.

The best defensible current statement is:

> A properly configured 8-vCPU Amphora reached **~128k sustainable plain-HTTP 1-KiB RPS** in the clean three-run adaptive benchmark, with **6 ms accepted/best p99, 0% failures, and healthy generator headroom**. In the homogeneous September core matrix, Elite measured **~93.2k plain HTTP**, **~141.0k TLS passthrough**, **~73.9k TLS termination**, and **~64.6k TLS termination + re-encryption** median peak RPS. The separate Elite-only concurrency staircase independently peaked at **126.7k RPS at 750 users**, stayed near ~122k through 1500 users, then traded throughput for latency at 2000-4000 users with zero failures. These are workload-specific observations, not one universal RPS rating.

That does **not** make Rackspace universally faster or cheaper than public-cloud alternatives. Architectures, HA semantics, autoscaling, global reach, TLS behavior, bandwidth, and SLA models differ.

It does mean the Amphora offering now has a credible performance basis for differentiated Pro and Elite tiers. The next pricing refinement should add current-MQ CPS, simultaneous-connection, and dedicated-bandwidth campaigns, while preserving the completed TLS request-rate matrix and the separate Elite concurrency-saturation diagnostic.

---

# Sources

1. DigitalOcean, **Load Balancers Pricing**, current 2026 documentation.  
   https://docs.digitalocean.com/products/networking/load-balancers/details/pricing/

2. DigitalOcean, **Introducing new DigitalOcean Load Balancers for higher-scale business applications**, December 8, 2020. Historical synthetic HTTPS benchmark: 8.3k / 23.9k / 41.9k RPS for old S/M/L plans.  
   https://www.digitalocean.com/blog/introducing-new-digitalocean-load-balancers-plans

3. Scaleway, **Network Pricing — Load Balancer**, current September 2026 pricing page.  
   https://www.scaleway.com/en/pricing/network/

4. Scaleway, **Load Balancer limitations**, reviewed May 6, 2026.  
   https://www.scaleway.com/en/docs/load-balancer/reference-content/load-balancers-limitations/

5. Akamai Cloud / Linode, **NodeBalancers**, current 2026 documentation.  
   https://techdocs.akamai.com/cloud-computing/docs/nodebalancer

6. Akamai Cloud / Linode, **Available protocols**, current 2026 documentation.  
   https://techdocs.akamai.com/cloud-computing/docs/available-protocols

7. Vultr, **How Are Vultr Load Balancers Priced?**, updated December 16, 2025.  
   https://docs.vultr.com/support/platform/billing/how-are-vultr-load-balancers-priced

8. Vultr, **How Is Bandwidth Charged for Vultr Load Balancers?**, updated April 15, 2026.  
   https://docs.vultr.com/support/products/load-balancer/how-is-bandwidth-charged-for-vultr-load-balancers

9. Hetzner, **Load Balancer FAQ**, current 2026 documentation.  
   https://docs.hetzner.com/networking/load-balancers/faq/

10. Hetzner, **Load Balancer product page**, current 2026.  
    https://www.hetzner.com/cloud/load-balancer/

11. AWS, **Elastic Load Balancing pricing**, current 2026.  
    https://aws.amazon.com/elasticloadbalancing/pricing/

12. Google Cloud, **Cloud Load Balancing pricing**, current 2026.  
    https://cloud.google.com/load-balancing/pricing

13. Google Cloud, **Proxy-only subnets for Envoy-based load balancers**, current 2026.  
    https://cloud.google.com/load-balancing/docs/proxy-only-subnets

14. Microsoft, **Understanding pricing — Azure Application Gateway**, current 2026.  
    https://learn.microsoft.com/en-us/azure/application-gateway/understanding-pricing

15. Microsoft, **What is Azure Application Gateway v2?**, current 2026.  
    https://learn.microsoft.com/en-us/azure/application-gateway/overview-v2

16. Rackspace Spot, **Pricing**, current 2026.  
    https://spot.rackspace.com/docs/en/pricing

17. Rackspace OpenStack Documentation, **Octavia CLI Load Balancer Setup Guide**, current 2026; default Rackspace provider documented as Amphora.  
    https://docs.rackspacecloud.com/octavia-loadbalancer-setup-guide/

---

# Calculation notes

- Monthly normalized comparisons use **730 hours/month** unless a provider publishes a different billing example convention.
- DigitalOcean equivalent nodes are `ceil(reference_RPS / 10,000)`.
- 1-KiB payload throughput is `RPS x 1,024 bytes x 8` and excludes headers/protocol overhead.
- AWS illustrative LCU cost uses only 1-KiB response payload and the documented 1 GB/hour per LCU byte dimension; it intentionally omits request bytes, headers, internet egress, and rule costs.
- GCP illustrative cost uses only response payload, current $0.008/GiB US regional processing, and one $0.025/hour forwarding rule; actual product/region/direction charges can differ.
- All external vendor RPS/capacity figures are vendor-published sizing/maximum/capacity signals, not independently benchmarked under the Rackspace harness.
