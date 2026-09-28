# Octavia Amphora Market Comparables and Pricing Position — September 2026

**Status:** Updated after September 18, 2026 full-flavor / multi-scenario campaign
**Benchmark date:** 2026-09-18 UTC
**Scope:** Rackspace Amphora/HAProxy service positioning, public cloud comparables, price/capacity signals, and measured scenario envelopes
**Important:** This is a market-positioning document, not a final price book or performance SLA. The September 18 campaign adds materially stronger evidence for Pro/Elite differentiation, but TLS CPS, connection churn/capacity, bandwidth, floating-IP path, host-density, and HA/failover campaigns remain open.

---

# 1. Executive update

The September 18 campaign materially strengthens the case for differentiated Amphora flavors. The new data should **not** be reduced to a single RPS number: the workload shape changes the useful capacity substantially.

## Current measured HTTP/TLS scenario envelope

The table below uses the September 18 three-run matrix supplied from `comparison-summary.csv`. `median_primary` is the reported scenario primary metric (`peak_rps_history`) for the normal staircase campaign; it is **not** the same metric as `max_sustainable_rps` from an adaptive max-RPS search.

| Scenario | Lite | Plus | Pro | Elite | Elite/Pro | Elite p99 | Elite failures | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| HTTP 1-KiB keepalive | 13,470 RPS | 16,112 RPS | 57,309 RPS | **93,181 RPS** | **1.63x** | 130 ms | 0% | Elite max across runs reached 126,723 RPS; high run-to-run spread means staircase peak is not a single fixed ceiling. |
| TLS passthrough 1-KiB keepalive | 25,930 RPS | 23,221 RPS | 72,766 RPS | **140,975 RPS** | **1.94x** | 98 ms | 0% | Strongest Elite scenario; no reported failures at the primary result. |
| TLS termination 1-KiB keepalive | 9,920 RPS | 12,248 RPS | 40,779 RPS | **73,892 RPS** | **1.81x** | 160 ms | 0% | Crypto termination materially lowers absolute RPS versus passthrough, as expected. |
| TLS termination + backend re-encryption | 10,330 RPS | 14,323 RPS | 47,634 RPS | **64,592 RPS** | **1.36x** | 180 ms | 0.184% | Pro/Plus had much higher failure percentages in this campaign; re-encryption is currently the harshest normal scenario. |

These scenario-specific values are more appropriate for product sizing than a single global “Elite RPS” claim. In particular, **Elite is not universally 2x Pro**: it is ~1.94x in TLS passthrough, ~1.81x in TLS termination, ~1.63x in plain HTTP, and ~1.36x with backend re-encryption in this campaign.

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

At the clean Elite result, one active Amphora is delivering roughly the HTTP request-rate class that DigitalOcean exposes through **13 capacity nodes**.

That does not automatically mean Elite should cost $156/month. It means that a single-active Elite list price in roughly the low-to-mid hundreds per month can be justified in market terms if the remaining TLS/connection/bandwidth tests are similarly strong.

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
| **Rackspace Octavia Elite MQ** | Proposed flat flavor; clean adaptive HTTP reference **~127.8k median sustainable RPS**; September normal-staircase peaks: HTTP **93.2k**, TLS passthrough **141.0k**, TLS termination **73.9k**, re-encryption **64.6k** | Market-positioning band currently **~$125-$165/mo** single-active | Strongest differentiated tier. Roughly 2x Pro in passthrough and termination, but only ~1.36x in re-encryption; future price/product claims should use per-scenario envelopes rather than one universal RPS number. |

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

# 13.1 Scenario-aware capacity is now part of the product story

The September 18 campaign shows that the same Amphora flavor can have very different useful capacity depending on dataplane mode. The largest Elite/Pro separation is TLS passthrough (~1.94x), followed by TLS termination (~1.81x), plain HTTP (~1.63x), and full re-encryption (~1.36x).

This suggests the eventual product matrix should avoid a single undifferentiated “RPS” promise. A better customer-facing model is a reference envelope by feature class:

```text
HTTP/L7 keepalive       -> reference RPS
TLS passthrough         -> reference RPS + CPS/connection tests
TLS termination         -> reference RPS + full-handshake CPS
TLS re-encryption       -> reference RPS + backend TLS behavior
connection churn        -> new connection/sec + p99
active connections      -> simultaneous connection envelope
bandwidth workloads     -> payload Gbit/s + packet-rate envelope
```

The April/September public-comparator work therefore remains useful, but each external mapping should be clearly tied to a workload class. DigitalOcean's public 10k RPS/node number is strongest as a plain HTTP sizing anchor, while its published SSL-CPS and connection limits are better anchors for TLS and connection-focused comparisons.

# 13. What the new results change about product strategy

## 13.1 Elite is now a real product, not just a larger VM

Before MQ, Elite's ~58k RPS made it difficult to justify a large premium over Pro. The new ~128k result changes that completely.

The current HTTP result supports a clear customer story:

- Pro: high-density, strong application LB capacity;
- Elite: approximately 2.12x Pro on the separate clean adaptive HTTP max-RPS benchmark; the normal staircase shows a more conservative ~1.63x Elite/Pro ratio for the reported peak-RPS metric;
- both: fixed capacity-flavor pricing rather than opaque request/byte billing.

## 13.2 Vertical scaling is currently economically credible

The clean adaptive 4->8 vCPU result is ~2.12x sustainable HTTP RPS for 2x guest vCPU. The normal staircase gives ~1.63x for its reported peak-RPS metric. Both point to meaningful vertical scaling after multiqueue, but the two metrics should not be conflated.

The next question is no longer “does 8 vCPU help?” It is:

> At what flavor size does vertical scaling stop being cheaper than horizontal active-active architecture?

That breakpoint still needs 16-vCPU experiments, host NUMA/locality testing, and potentially a multi-active architecture study.

## 13.3 MQ should be treated as a product prerequisite

The competitive conclusion depends on a correctly configured dataplane. The old single-queue Elite result would have materially underpriced or over-resourced the product if used for commercial sizing.

Virtio MQ exposure and active queue count should therefore become part of Amphora image/flavor acceptance testing, not an optional tuning detail.

## 13.4 Publish a reference envelope, not only vCPU count

Most customers do not care that Elite has 8 vCPU. They care what it can do.

A strong Rackspace product page could eventually publish a tested reference envelope such as:

| Dimension | Standard | Pro | Elite |
|---|---:|---:|---:|
| Reference HTTP RPS | measured | ~60k adaptive / ~57k normal staircase | ~128k adaptive / ~93k normal staircase |
| Reference HTTPS termination RPS | TBD | TBD | TBD |
| TLS CPS | TBD | TBD | TBD |
| TCP CPS | TBD | TBD | TBD |
| Simultaneous connections | TBD | TBD | TBD |
| Reference payload throughput | TBD | TBD | TBD |
| Reference p99 | measured | measured | 6 ms current HTTP point |
| CPU placement / consistency | shared candidate | mixed candidate | dedicated candidate |

The word **reference** is important. Until enforcement/SLO semantics are designed, these should be published as sizing guidance under a defined benchmark workload rather than unconditional guarantees.

---

# 14. Remaining evidence required before final pricing

The new HTTP result is strong enough to change positioning, but it is not enough to finalize the price book.

The following campaigns still materially affect customer value and cost:

1. **TLS termination max RPS** — probably the most important next commercial comparator.
2. **TLS full-handshake CPS** — expensive crypto path and a common published competitor limit.
3. **TLS resumed-session CPS**.
4. **HTTP/TCP connection churn**.
5. **maximum simultaneous active connections**.
6. **64-KiB / 1-MiB bandwidth ceilings**.
7. **floating-IP/public path performance** rather than only tenant-VIP.
8. **connection logging on/off**.
9. **ACTIVE_STANDBY failover behavior under load**.
10. **host-density/noisy-neighbor tests** for Standard/Pro economics.
11. **dedicated PCPU / NUMA-local Elite validation** if Elite will carry a premium consistency claim.
12. **multi-Amphora-per-host stress** to determine actual sellable host density and gross margin.

If Elite's TLS/CPS envelope scales similarly to HTTP, the current provisional $125-$165 single-active market band becomes significantly easier to defend. If TLS scaling is materially weaker, the product should be positioned as a high-RPS HTTP/application tier rather than a universally 2x tier.

---

# 15. Current conclusion

The new multiqueue data changes the competitive assessment in Rackspace's favor.

The best defensible current statement is:

> A properly configured 8-vCPU Amphora reached **~128k sustainable plain-HTTP 1-KiB RPS** in the clean three-run adaptive benchmark, with **6 ms best p99, 0% failures, and healthy generator headroom**; that is roughly **2.12x** the established 4-vCPU Pro MQ adaptive result. The September normal staircase separately reports **~93k median peak HTTP RPS for Elite versus ~57k for Pro** (~1.63x). The adaptive ~128k figure maps to roughly **13 DigitalOcean 10k-RPS capacity nodes**, while the normal-staircase ~93k figure maps to roughly **10 nodes**. Neither is a product-equivalence claim; these are workload-specific market-sizing anchors.

That does **not** make Rackspace universally faster or cheaper than those providers. Their architectures, HA semantics, global reach, TLS behavior, autoscaling, bandwidth, and SLAs are different.

It does mean that the Amphora offering now has a credible performance basis for differentiated Pro and Elite tiers, and the fixed-price model can be commercially compelling for customers with sustained high-volume traffic.

The next major pricing update should happen after the current user-concurrency diagnostic and the first clean TLS termination/CPS results.

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
