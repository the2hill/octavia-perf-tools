# Cloud Load Balancer Competitive Capacity and Cost Reference

**Status:** working competitive-research document  
**Last verified:** 2026-08-26  
**Purpose:** provide a defensible reference for comparing our OpenStack Octavia service against major public-cloud and independent-cloud load balancer offerings.

> **Important:** Published provider numbers are not all the same kind of number. Some are hard plan limits, some are billing-unit definitions, some are autoscaling sizing units, and some are merely service quotas. This document labels them explicitly so that we do not present a billing unit as a guaranteed performance limit.

## Executive summary

The most useful public comparisons fall into three categories:

| Model | Examples | What the vendor exposes |
|---|---|---|
| **Explicit per-node capacity** | DigitalOcean | RPS, simultaneous connections, new SSL connections/sec, cost per node |
| **Managed capacity/billing units** | AWS ALB/NLB, Azure Application Gateway | Connection, throughput, and/or compute dimensions used for billing and scaling |
| **Managed proxy instance capacity** | Google Cloud regional Envoy-based LBs | Per-proxy RPS, connections, connection establishment rate, bandwidth, and proxy-hour price |
| **Bandwidth-shaped service** | OCI Flexible Load Balancer | Guaranteed minimum and configured maximum Mbps; CPU is hidden |
| **Fixed connection-tier service** | Akamai NodeBalancer, Hetzner Cloud Load Balancer | Concurrent-connection limits and plan price/tier; underlying CPU generally hidden |

For our benchmarking program, the strongest apples-to-apples competitive metrics are:

1. HTTP/HTTPS requests per second at an explicit p99 latency gate.
2. New TCP connections/sec.
3. New TLS connections/sec with a documented key type.
4. Maximum sustained concurrent connections.
5. Application payload throughput and observed NIC throughput.
6. CPU/compute utilization or provider capacity-unit utilization.
7. Burst behavior and time-to-scale.
8. Cost at the measured load, not only idle/base price.

---

## Our current Octavia baseline

This is an **observed internal benchmark**, not a vendor marketing claim.

| Item | Current baseline |
|---|---|
| Octavia flavor | `amphora-default` |
| Amphora Nova flavor | `gp.0.1.4` |
| Compute | **1 vCPU, 4 GiB RAM, 10 GiB disk** |
| CPU generation constraint | AMD EPYC 75F3 aggregate |
| VIF outbound average | `250000` kB/s, approximately 2 Gbit/s |
| VIF outbound peak | `500000` kB/s, approximately 4 Gbit/s |
| HTTP direct-backend control | ~87,156 RPS at 500 Locust users, 0 failures |
| HTTP through Octavia, highest observed RPS | ~11,080 RPS at 500 users |
| HTTP high-concurrency plateau | ~8.2-8.4k RPS |
| Amphora guest vCPU during saturated run | ~99.9-100% |
| Amphora vCPU scheduler delay | ~0.02-0.04%; host scheduling contention negligible |
| Current conclusion | 1-vCPU amphora is CPU-bound before backend/client capacity is reached |

The baseline therefore gives us a transparent compute-to-performance relationship that most managed competitors do **not** expose directly.

Fields still to populate as the benchmark campaign completes:

- maximum sustained HTTP simultaneous connections;
- maximum active TLS passthrough connections;
- maximum TLS-termination connections;
- HTTP connection-churn/CPS ceiling;
- TLS passthrough CPS ceiling;
- TLS termination CPS ceiling;
- sustained 64 KiB / 1 MiB payload throughput;
- external/FIP-path results;
- customer-facing monthly price for each Octavia flavor.

---

# Primary competitors

## AWS Elastic Load Balancing

### Relevant products

- **Application Load Balancer (ALB):** Layer 7 HTTP/HTTPS, TLS termination, routing rules.
- **Network Load Balancer (NLB):** Layer 4 TCP/UDP/TLS, high connection scale and low-latency forwarding.

AWS does not publish the underlying vCPU/RAM configuration. Capacity is abstracted behind LCUs/NLCUs and automatic scaling.

### AWS ALB published billing dimensions

One ALB **LCU** contains the following. Billing uses whichever dimension is highest:

| Dimension | 1 LCU |
|---|---:|
| New connections | 25/sec |
| Active connections | 3,000 |
| Processed bytes | 1 GB/hour for EC2/container/IP targets |
| Rule evaluations | 1,000/sec after the first 10 processed rules |

For HTTPS, the 25-new-connections/sec figure applies to RSA certificates <= 2048 bits and ECDSA <= 256 bits. Larger keys consume more capacity.

**US-East-1 example pricing published by AWS:**

- load balancer: **$0.0225/hour**
- LCU: **$0.008/LCU-hour**

Normalized to 730 hours:

- fixed LB charge: **$16.43/month**
- each continuously consumed LCU: **$5.84/month**

### AWS NLB published billing dimensions

For TCP, one NLCU contains:

| Dimension | 1 NLCU |
|---|---:|
| New TCP flows | 800/sec |
| Active TCP flows | 100,000 |
| Processed bytes | 1 GB/hour |

For TLS listeners:

| Dimension | 1 NLCU |
|---|---:|
| New TLS flows | 50/sec |
| Active TLS flows | 3,000 |
| Processed bytes | 1 GB/hour |

**US-East-1 example pricing published by AWS:**

- load balancer: **$0.0225/hour**
- NLCU: **$0.006/NLCU-hour**

Normalized to 730 hours:

- fixed LB charge: **$16.43/month**
- each continuously consumed NLCU: **$4.38/month**

### AWS cost normalization examples

These examples isolate one billing dimension and assume it dominates. They are **not AWS maximum-capacity claims**.

| Workload | Approximate LB charge/month |
|---|---:|
| ALB, 10,000 active connections | $35.89 |
| ALB, 1,000 new connections/sec | $250.03 |
| NLB TCP, 100,000 active connections | $20.80 |
| NLB TCP, 1,000 new connections/sec | $21.90 |
| NLB TLS, 1,000 new TLS connections/sec | $104.02 |

Data processing and normal AWS data-transfer charges can dominate these examples at high throughput.

### Compute visibility

**Low.** AWS exposes no customer-visible ELB vCPU/RAM shape. LCUs/NLCUs describe billable traffic dimensions rather than a physical compute allocation.

### Benchmark implications

- Do **not** compare our `11k RPS on 1 vCPU` directly to `1 LCU`; LCU is not a claim that an ALB tops out at that level.
- Useful AWS comparison tests are measured ALB/NLB RPS, CPS, concurrency and cost at the same workload.
- AWS now supports capacity reservations for some ELB products. For NLB reservation, AWS documents a throughput conversion of approximately **1 reserved LCU = 2.2 Mbps**; NLB TLS listeners are excluded from NLB LCU reservation.
- For cost analysis, capture CloudWatch `ConsumedLCUs`/equivalent usage along with benchmark results.

**Official sources**

- [AWS Elastic Load Balancing pricing](https://aws.amazon.com/elasticloadbalancing/pricing/)
- [AWS NLB capacity-unit reservation](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/request-capacity-unit-reservation.html)
- [AWS ALB quotas](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-limits.html)
- [AWS NLB quotas](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/load-balancer-limits.html)

---

## Microsoft Azure

### Relevant products

- **Azure Standard Load Balancer:** managed Layer 4 TCP/UDP service.
- **Azure Application Gateway Standard_v2:** Layer 7 HTTP/HTTPS plus TCP/TLS proxy support, TLS termination, autoscaling, routing, and optional WAF tier.

For comparison with Octavia's HAProxy/amphora TLS and HTTP behavior, **Application Gateway Standard_v2** has the more useful public compute/capacity data.

### Application Gateway Standard_v2 published capacity

Azure exposes a synthetic **Compute Unit** and **Capacity Unit**, rather than vCPU/RAM.

For Standard_v2:

| Metric | Published value |
|---|---:|
| New connections/sec per compute unit | **50/sec** |
| Throughput per capacity unit | **2.22 Mbps** |
| Persistent connections per capacity unit | **2,500** |
| Published Standard_v2 max new connections/sec | **62,500/sec** with RSA-2048 estimate |
| Persistent connections per Standard_v2 instance | **25,000** |
| Throughput per Standard_v2 instance | **500 Mbps** |
| Compute units per Standard_v2 instance | **10** |

Azure notes that compute-unit consumption is influenced by TLS connection rate, URL rewrite work, and WAF rule processing.

### Azure pricing

Microsoft's East US Standard_v2 pricing examples publish:

- fixed gateway charge: **$0.246/hour**
- Standard_v2 capacity unit: **$0.008/CU-hour**

Normalized to 730 hours:

- fixed gateway: **$179.58/month**
- each continuously billed CU: **$5.84/month**

A manually provisioned Standard_v2 instance reserves 10 CUs, which gives an approximate baseline cost of:

**$237.98/month** before public-IP and outbound data-transfer charges.

### Azure cost normalization examples

| Workload | Capacity-unit interpretation | Approximate Standard_v2 charge/month |
|---|---:|---:|
| 10,000 persistent connections | 4 CU | $202.94 |
| 1,000 new TLS connections/sec | 20 CU | $296.38 |
| 500 Mbps if throughput is dominant | ~225.2 CU | $1,494.90 |

The 500-Mbps example illustrates an important Azure characteristic: an instance can physically handle far more throughput capacity units than its 10-CU compute/persistent-connection baseline. Billing is based on the highest consumed/reserved capacity dimension.

### Azure Standard Load Balancer

Azure describes Standard Load Balancer as a fully managed service that scales to **millions of TCP/UDP flows** without a customer-visible instance concept. Pricing is per configured rule and per GB processed; the precise current rate should be pulled from the live Azure pricing page/calculator for the target region when we run a formal comparison.

### Compute visibility

**Medium.**

- No vCPU/RAM is disclosed.
- Application Gateway publishes compute units and instance-level capacity envelopes.
- Standard Load Balancer exposes no instance shape.
- Application Gateway metrics expose current capacity units, compute units, and current connections, which is useful for reproducing our Prometheus/libvirt CPU correlation concept.

### Benchmark implications

Application Gateway is one of the strongest managed-service comparisons for our Octavia flavor model because Azure publishes:

- a per-instance capacity envelope;
- a compute-like unit;
- connection and throughput dimensions;
- a direct consumption-based price.

**Official sources**

- [Azure Application Gateway v2 overview and capacity](https://learn.microsoft.com/en-us/azure/application-gateway/overview-v2)
- [Azure Application Gateway pricing model](https://learn.microsoft.com/en-us/azure/application-gateway/understanding-pricing)
- [Azure Application Gateway monitoring metrics](https://learn.microsoft.com/en-us/azure/application-gateway/monitor-application-gateway-reference)
- [Azure application-delivery design guide](https://learn.microsoft.com/en-us/azure/networking/design-guide/app-delivery)
- [Azure Load Balancer pricing](https://azure.microsoft.com/en-us/pricing/details/load-balancer/)

---

## Google Cloud

### Relevant products

Google Cloud offers multiple Application and Network Load Balancers. The most transparent capacity data is published for the **regional Envoy-based proxy fleet** used by regional/internal managed proxy load balancers.

### Published proxy-instance capacity

Google publishes the following per managed proxy instance:

| Metric | Per proxy instance |
|---|---:|
| Bandwidth | **18 MB/sec** (~144 Mbps) |
| New HTTP connections | **600/sec** |
| New HTTPS connections | **150/sec** |
| Active connections | **3,000** |
| HTTP requests | **1,400 RPS** with logging disabled |
| HTTP requests with 100% logging example | **~700 RPS** |

Google evaluates the required proxy count over a 10-minute period and uses the greatest required count among bandwidth, new connections, active connections, and requests.

This is especially valuable because it closely resembles an abstracted version of our amphora-flavor approach: a managed proxy unit has explicitly documented traffic capacity even though its underlying CPU/RAM is hidden.

### Pricing for regional/internal proxy-based Application Load Balancers

Published US pricing:

- **$0.025/proxy-hour**
- **$0.008/GiB processed**

One continuously required proxy therefore costs approximately **$18.25/month**, excluding data processing and transfer.

### GCP cost normalization examples

The following use only the proxy-hour component; data processing is additional.

| Workload | Required proxies from published capacity | Proxy charge/month |
|---|---:|---:|
| 10,000 RPS, logging disabled | 8 | $146.00 |
| 10,000 RPS, 100% logging | 15 | $273.75 |
| 10,000 active connections | 4 | $73.00 |
| 1,000 new HTTPS connections/sec | 7 | $127.75 |

### External Application Load Balancer pricing

Google also publishes, for common US regions:

- first five forwarding rules: **$0.025/hour**
- inbound data processed: **$0.008/GiB**
- outbound data processed: **$0.008/GiB**
- normal internet egress is separate.

These charges differ from the internal proxy-instance model, so we must select the exact GCP product topology before comparing costs.

### Burst behavior

Google explicitly states that regional proxy capacity automatically expands and that customers expecting bursts beyond **100,000 QPS** can contact support to pre-warm the regional proxy pool.

That is a useful competitive metric beyond steady-state throughput: **how quickly does the managed service absorb a large step change in load?**

### Compute visibility

**Medium.**

- No vCPU/RAM.
- Very useful per-proxy RPS/CPS/concurrency/bandwidth figures.
- Logging has a documented material effect on request-handling capacity.

**Official sources**

- [Google Cloud Load Balancing pricing](https://cloud.google.com/load-balancing/pricing)
- [Google proxy-only subnet and proxy-capacity documentation](https://cloud.google.com/load-balancing/docs/proxy-only-subnets)
- [Google Cloud Load Balancing quotas and limits](https://cloud.google.com/load-balancing/docs/quotas)
- [Google backend-service balancing modes](https://cloud.google.com/load-balancing/docs/backend-service)

---

## DigitalOcean

DigitalOcean currently provides unusually clear per-node limits, making it one of the easiest competitors to normalize.

### Regional HTTP Load Balancer

Each node costs **$12/month** and increases the documented maximum by:

| Metric | Per $12/month node |
|---|---:|
| HTTP requests/sec | **10,000 RPS** |
| Simultaneous connections | **10,000** |
| New SSL connections/sec, normal certificate | **250/sec** |
| New SSL connections/sec, RSA-4096 | **50/sec** |

DigitalOcean allows scaling to as many as 200 nodes where account limits permit.

Simple dollar normalization:

| Capacity dimension | Published cost mapping |
|---|---:|
| 10,000 RPS | **$12/month** |
| 10,000 simultaneous connections | **$12/month** |
| 1,000 new SSL connections/sec | **$48/month** using 4 nodes |
| 100,000 simultaneous connections | **$120/month** using 10 nodes |

DigitalOcean warns that actual performance varies by workload and recommends benchmarking.

### Regional Network Load Balancer

- **$15/month per node**
- each node adds **50 Mbps ingress throughput**
- DigitalOcean states there is **no defined upper connection or RPS limit** for the network load balancer.

That works out to a published capacity-price ratio of **$0.30/month per Mbps of provisioned ingress increment**, before backend/egress considerations.

### Global Load Balancer

The Global Load Balancer is currently **$15/month**, including:

- 25 million HTTP/HTTPS requests/month;
- 1 TB transfer/month;
- 5 connected domains.

Overages are $0.70 per additional million requests and $0.02/GB transfer.

This product is more comparable to global traffic management than to a regional Octavia amphora.

### Compute visibility

**Medium-low.**

- vCPU/RAM per node are not published.
- Each node is a concrete scale unit with explicit performance limits.
- DigitalOcean's Insights can expose **Load Balancer CPU Utilization** for some regional load balancers, making it possible to correlate an actual benchmark with LB CPU even though the physical shape is hidden.

### Benchmark implications

DigitalOcean gives us a direct target:

> Can one of our priced Octavia flavors deliver better than 10k RPS, 10k simultaneous connections, and/or 250 new TLS connections/sec at a competitive monthly price?

Our current 1-vCPU HTTP result is already close to their published single-node 10k-RPS envelope, which makes the eventual 2-vCPU and larger-flavor comparisons particularly useful.

**Official sources**

- [DigitalOcean regional/global load balancer pricing](https://docs.digitalocean.com/products/networking/load-balancers/details/pricing/)
- [DigitalOcean load balancer limits](https://docs.digitalocean.com/products/networking/load-balancers/details/limits/)
- [DigitalOcean scaling documentation](https://docs.digitalocean.com/products/networking/load-balancers/how-to/scale/)
- [DigitalOcean Load Balancer Insights](https://docs.digitalocean.com/products/networking/load-balancers/how-to/manage/)

---

## Oracle Cloud Infrastructure (OCI)

OCI exposes **bandwidth shapes** for its Flexible Load Balancer instead of CPU/RPS capacity.

### Flexible Load Balancer capacity

Flexible shapes let the user configure:

- minimum bandwidth: **10 Mbps or greater**
- maximum bandwidth: up to **8,000 Mbps**

The minimum bandwidth is pre-provisioned/guaranteed capacity. The maximum is the scaling ceiling and is not necessarily guaranteed.

OCI describes the shape as total ingress + egress capacity.

### Pricing model

Oracle's global price list publishes:

- first load balancer instance/month: Free Tier allowance
- additional Load Balancer Base: **$0.0113/hour**
- first 10 Mbps/hour: Free Tier allowance
- bandwidth above the first 10 Mbps: **$0.0001 per Mbps-hour**

Billing is per minute and is based on the greater of configured minimum bandwidth or actual bandwidth usage for the minute.

Example approximate 730-hour bandwidth costs:

| Sustained billed bandwidth | Bandwidth component/month | Plus additional-LB base if applicable |
|---:|---:|---:|
| 100 Mbps | $6.57 | +$8.25 |
| 500 Mbps | $35.77 | +$8.25 |
| 1,000 Mbps | $72.27 | +$8.25 |
| 8,000 Mbps | $583.27 | +$8.25 |

These figures are useful for our 64-KiB/1-MiB throughput scenarios, but OCI does not provide a corresponding public RPS or TLS-CPS claim.

### OCI Network Load Balancer

OCI markets its Flexible Network Load Balancer as **no additional charge** for the load-balancer service itself. Normal network/data-transfer/backend costs still matter. OCI does not publish a simple numeric RPS/concurrency ceiling suitable for this table.

### Compute visibility

**Low.** CPU and RAM are hidden; customer-visible capacity is bandwidth-oriented.

**Official sources**

- [OCI Flexible Load Balancer creation and bandwidth shapes](https://docs.oracle.com/en-us/iaas/Content/Balance/Tasks/managingloadbalancer_topic-Creating_Load_Balancers.htm)
- [OCI Load Balancer concepts](https://docs.oracle.com/en-us/iaas/Content/Balance/Concepts/balanceoverview_topic-Load_Balancing_Concepts.htm)
- [Oracle cloud price list](https://www.oracle.com/cloud/price-list/)
- [OCI Flexible Network Load Balancer](https://www.oracle.com/cloud/networking/flexible-network-load-balancer/)

---

## Akamai Cloud / Linode NodeBalancer

### Basic NodeBalancer

Published specifications:

| Metric | Basic NodeBalancer |
|---|---:|
| Price | **$10/month**, approximately $0.015/hour |
| Concurrent TCP/HTTP/HTTPS connections | **up to 10,000** |
| Maximum inbound network bandwidth | **10 Gbps** |
| Backend nodes/configuration | up to 1,000 |
| Infrastructure | shared |
| New connection rate | no defined rate limit |

Akamai explicitly notes that HTTPS termination is the most resource-intensive protocol mode and accommodates fewer connections/sec than TCP.

Dollar normalization:

- **$1/month per 1,000 published concurrent connections**
- nominal **$1/month per Gbps** if one divides price by the published 10-Gbps inbound ceiling, though that should not be treated as guaranteed dedicated bandwidth because the Basic service uses shared infrastructure.

### Premium NodeBalancer

- up to **100,000 concurrent TCP/HTTP/HTTPS connections**
- up to **80,000 UDP connections**
- **10 Gbps** inbound network bandwidth
- dedicated infrastructure
- up to 2,000 backends/configuration
- pricing: contact sales
- currently limited to LKE Enterprise.

### Compute visibility

**Low-medium.**

Akamai does not publish vCPU/RAM, but it explicitly distinguishes Basic **shared** infrastructure from Premium **dedicated** infrastructure.

**Official sources**

- [Akamai NodeBalancer specifications and pricing](https://techdocs.akamai.com/cloud-computing/docs/nodebalancer)
- [Akamai NodeBalancer protocols](https://techdocs.akamai.com/cloud-computing/docs/available-protocols)
- [Akamai North America cloud pricing](https://www.akamai.com/cloud/pricing/north-america)
- [Akamai NodeBalancer metrics](https://techdocs.akamai.com/cloud-computing/docs/nodebalancers-metrics)

---

## Hetzner Cloud Load Balancer

Hetzner publishes tiered concurrent-connection capacity:

| Plan | Concurrent open connections |
|---|---:|
| LB11 | **10,000** |
| LB21 | **20,000** |
| LB31 | **40,000** |

Hetzner states:

- larger plans receive more CPU and memory;
- the actual CPU/RAM quantities are not disclosed;
- bandwidth is not explicitly limited;
- load balancers on a physical node share a **2x10 Gbit** interface;
- there is no explicit new-connections/sec limit; connection rate is constrained by system resources;
- TLS termination changes attainable performance.

Traffic allowances vary by network zone. Hetzner documentation lists 20 TB for EU Cloud Load Balancers and 1-3 TB for US/Singapore locations.

### Compute visibility

**Medium-low.**

Hetzner explicitly confirms that the tiers differ in CPU and RAM, which is useful conceptually, but does not publish the actual values. This is closer to our Octavia flavor model than AWS, but our model is considerably more transparent because users/operators can see the Nova flavor.

### Pricing note

Hetzner's live product page uses location/currency-dependent pricing and the machine-readable page does not reliably expose the numeric current plan prices. For a formal cost table, capture the live LB11/LB21/LB31 price for the exact comparison region on the benchmark date rather than hard-coding a potentially stale value here.

**Official sources**

- [Hetzner Load Balancer performance FAQ](https://docs.hetzner.com/networking/load-balancers/faq/)
- [Hetzner Load Balancer product page](https://www.hetzner.com/cloud/load-balancer/)
- [Hetzner traffic allowances](https://docs.hetzner.com/robot/general/traffic/)

---

# Secondary competitor: Vultr

Vultr is useful as a price/feature comparison, but its public documentation currently provides less quantitative capacity data.

Published items:

- load balancers start at **$10/month per instance**;
- customers can resize by changing the number of LB nodes;
- TCP, HTTP, and HTTPS are supported;
- TLS termination is supported;
- load-balancer traffic does not incur a separate bandwidth charge; backend instance egress applies;
- Vultr says it manages the underlying infrastructure and scaling;
- no clear public RPS, CPS, concurrent-connection, per-node bandwidth, vCPU, or RAM envelope was found in current official documentation.

For performance-per-dollar rankings, mark Vultr **N/A until directly benchmarked or until Vultr publishes a quantitative service envelope**.

**Official sources**

- [Vultr Load Balancer documentation](https://docs.vultr.com/products/network/load-balancer)
- [Vultr LB pricing explanation](https://docs.vultr.com/support/platform/billing/how-are-vultr-load-balancers-priced)
- [Vultr LB bandwidth charging](https://docs.vultr.com/support/products/load-balancer/how-is-bandwidth-charged-for-vultr-load-balancers)
- [Vultr LB resizing](https://docs.vultr.com/products/network/load-balancer/management/resize)

---

# Cross-provider capacity table

`N/P` means the provider does not publish a directly comparable numeric value.

| Provider / product | Layer | Compute/scale unit exposed | HTTP RPS claim | New TLS CPS claim | Concurrent connections | Throughput claim | Starting/base LB cost |
|---|---|---|---:|---:|---:|---:|---:|
| **Our Octavia baseline** | L4/L7 | **1 vCPU / 4 GiB** | **~11.1k observed peak; ~8.3k plateau** | testing in progress | testing in progress | testing in progress | TBD |
| AWS ALB | L7 | LCU; physical compute hidden | no hard RPS max | 25 new conn/s per LCU for common HTTPS cert sizes | 3k active/L CU | 1 GB/h processed/L CU | $0.0225/h + $0.008/L CU-h |
| AWS NLB TCP | L4 | NLCU; physical compute hidden | N/P | N/A for TCP | 100k/NLCU | 1 GB/h processed/NLCU | $0.0225/h + $0.006/NLCU-h |
| AWS NLB TLS | L4 TLS | NLCU | N/P | 50/NLCU | 3k/NLCU | 1 GB/h/NLCU | same |
| Azure App Gateway Standard_v2 | L7 + TCP/TLS | compute unit + CU | N/P | 50/sec per compute unit; service table says 62.5k max CPS | 2.5k/CU; 25k/instance | 2.22 Mbps/CU; 500 Mbps/instance | $0.246/h + $0.008/CU-h East US example |
| GCP regional Envoy proxy | L7/proxy | proxy instance | 1,400/proxy; ~700 with 100% logging | 150 HTTPS CPS/proxy | 3k/proxy | 18 MB/s/proxy | $0.025/proxy-h + $0.008/GiB |
| DigitalOcean Regional HTTP LB | managed HTTP | node | **10k/node** | **250/node**; 50 with RSA-4096 | **10k/node** | not expressed as HTTP bandwidth guarantee | **$12/node-month** |
| DigitalOcean Regional Network LB | L4 | node | no defined max | N/P | no defined max | **+50 Mbps ingress/node** | **$15/node-month** |
| OCI Flexible LB | L7/L4 proxy | Mbps shape | N/P | N/P | N/P | **10-8,000 Mbps** | base + $0.0001/Mbps-h above allowance |
| OCI Network LB | L4 | fully managed | N/P | N/P | N/P | N/P | **no LB service fee** |
| Akamai Basic NodeBalancer | L4/L7 | shared service | N/P | no defined CPS limit | **10k** | **10 Gbps inbound** | **$10/month** |
| Akamai Premium NodeBalancer | L4/L7 | dedicated service | N/P | no defined CPS limit | **100k TCP/HTTP/HTTPS** | **10 Gbps inbound** | contact sales |
| Hetzner LB11/LB21/LB31 | L4/L7 | increasing hidden CPU/RAM | N/P | no explicit limit | **10k / 20k / 40k** | shared-node 2x10G hardware envelope | region-dependent |
| Vultr Load Balancer | L4/L7 | node count; hidden compute | N/P | N/P | N/P | N/P | **from $10/month** |

---

# Compute transparency comparison

This deserves its own comparison because it affects how credible and reproducible capacity sizing is.

| Provider | CPU/RAM visibility | Performance-unit visibility | Can correlate load with LB CPU? |
|---|---|---|---|
| **Our Octavia** | **Full Nova flavor: vCPU/RAM/disk/QoS/CPU aggregate** | direct | **Yes: libvirt/Prometheus + guest behavior** |
| AWS | none | LCU/NLCU billing dimensions | no underlying LB CPU |
| Azure App Gateway | no vCPU/RAM | **compute units + capacity units + instance envelope** | partial: compute-unit metrics |
| GCP | no vCPU/RAM | **proxy-instance RPS/CPS/concurrency/bandwidth** | proxy count/capacity, not physical CPU |
| DigitalOcean | no vCPU/RAM | **node capacity limits** | CPU utilization metric available for some regional LBs |
| OCI | none | bandwidth shape | no |
| Akamai | none | shared vs dedicated + connection limits | metrics include sessions/traffic, not physical CPU |
| Hetzner | says larger plans get more CPU/RAM, values hidden | concurrent-connection tiers | no |
| Vultr | hidden | node count only | limited public capacity detail |

A potential product differentiator for us is therefore **transparent compute-backed flavor sizing**: a customer/operator can understand that a flavor is 1, 2, 4, or N vCPUs and can relate benchmark gains directly to compute.

---

# Cost-normalization rules for our benchmark reports

For each Octavia flavor and competitor, calculate all of the following where data is available:

```text
monthly_lb_cost
cost_per_10k_rps
cost_per_100k_concurrent_connections
cost_per_1k_new_tcp_cps
cost_per_1k_new_tls_cps
cost_per_gbps_sustained
```

Recommended formulas:

```text
cost_per_10k_rps =
    monthly_cost / (sustainable_rps / 10000)

cost_per_100k_connections =
    monthly_cost / (max_sustainable_connections / 100000)

cost_per_1k_tls_cps =
    monthly_cost / (sustainable_tls_cps / 1000)

cost_per_gbps =
    monthly_cost / sustained_gbps
```

Only calculate these against **measured sustainable levels that meet the same quality gates**.

Do not use an instantaneous peak if p99 latency or failures violate the benchmark criteria.

---

# Required apples-to-apples test profiles

Our current harness is already aligned with most of the capacity dimensions competitors publish.

| Competitive dimension | Harness scenario |
|---|---|
| HTTP RPS | `http_1k_max_rps` |
| HTTP steady-state staircase | `http_1k_keepalive` |
| New TCP connection pressure | `http_1k_connection_churn` |
| TLS passthrough RPS | `tls_passthrough_1k_max_rps` |
| TLS passthrough connection establishment | `tls_passthrough_1k_connection_churn` |
| TLS termination RPS | `tls_termination_1k_max_rps` |
| TLS termination connection establishment | `tls_termination_1k_connection_churn` |
| Active simultaneous HTTP connections | `http_connection_capacity_active` / max-connections variant |
| Active simultaneous TLS connections | TLS capacity scenarios |
| Bandwidth | 64-KiB / 1-MiB keepalive scenarios |
| Real-world north/south path | repeat suite with `benchmark.traffic_path: floating_ip` |

For TLS comparisons, standardize on a documented certificate type. **RSA-2048** is the most convenient common baseline because both AWS and Azure explicitly reference it in published capacity information.

---

# Proposed benchmark scorecard

For every provider/product or Octavia flavor, record:

| Field | Description |
|---|---|
| Product/SKU | Exact LB service and size/flavor |
| Region | Exact region/datacenter |
| Layer/protocol | HTTP, HTTPS termination, TLS passthrough, TCP |
| Compute unit | vCPU/RAM if visible; otherwise provider node/CU/proxy unit |
| Backend fleet | Same or equivalent backend capacity |
| Generator fleet | Client capacity and location |
| Traffic path | private/VIP vs public/FIP/internet |
| Payload | exact request and response bytes |
| TLS | protocol, cipher, cert algorithm/key size |
| Sustainable RPS | highest passing stage |
| p50/p95/p99 | latency at sustainable stage |
| Failure rate | at sustainable stage |
| New TCP CPS | sustained |
| New TLS CPS | sustained |
| Max active connections | idle and active |
| Sustained payload Gbps | application level |
| Network Gbps | actual NIC/service telemetry |
| LB CPU/compute | if exposed |
| Scale-out event | instance/proxy/node/CU change during run |
| Time to absorb burst | seconds/minutes |
| Base monthly cost | normalized |
| Usage-variable cost | LCU/CU/data/proxy charges |
| Egress cost | separate |
| Total modeled monthly cost | at tested workload |
| Cost efficiency | $/10k RPS, $/100k conn, $/1k TLS CPS, $/Gbps |

---

# Important comparison caveats

1. **Billing unit != hard capacity.** AWS LCU/NLCU quantities are primarily billing dimensions. Do not report “AWS ALB only supports 25 connections/sec”; it supports automatic scale-out and one LCU is merely the billing normalization.
2. **Logging/WAF changes capacity.** GCP explicitly documents a drop from 1,400 to about 700 RPS/proxy with 100% logging. Azure compute consumption is affected by WAF and rewrites. Keep feature sets aligned.
3. **TLS key size matters.** DigitalOcean explicitly drops from 250 to 50 new SSL CPS/node for RSA-4096; AWS and Azure also qualify TLS capacity by certificate characteristics.
4. **Connection reuse changes the meaning of RPS.** A 20k-RPS keepalive test may place very little connection-establishment pressure on the LB.
5. **External path and LB datapath are different populations.** Keep tenant-VIP and floating-IP/internet results separate.
6. **Backend and generator headroom must be proven.** Preserve direct baselines wherever the competitor topology permits them.
7. **Autoscaling introduces time.** Measure both steady-state capacity and response to a sudden load step.
8. **Monthly price alone is misleading.** AWS, Azure, GCP and OCI can have material variable usage charges; DigitalOcean/Akamai fixed-node pricing is easier to model.
9. **Data transfer is often separate.** Include egress, public IP, WAF/DDoS, certificate, and cross-zone/cross-region charges in a customer-price comparison.
10. **Provider claims should be archived with a date.** These services and prices change frequently.

---

# Recommended next research / validation work

1. Complete our 1-vCPU baseline matrix, including the public/FIP path.
2. Add 2-vCPU, 4-vCPU and larger Octavia flavors in the dedicated aggregate.
3. Capture libvirt vCPU saturation for every Octavia size to determine scaling efficiency.
4. Obtain customer-facing price for each Octavia flavor.
5. Build a generated `results/competitive-comparison.csv` containing the normalized cost metrics above.
6. Benchmark at least one external managed service directly if accounts are available:
   - DigitalOcean is the highest-value first external test because its published 10k RPS / 10k connections / 250 SSL CPS per $12 node is directly testable.
   - Azure Application Gateway is the strongest “compute unit” comparison.
   - GCP regional Envoy-based LB is the strongest proxy-unit comparison.
7. Add burst tests that jump from a low stable level directly to a high level and record time-to-recovery/scale-out.
8. Re-verify every provider source and price immediately before publishing any customer-facing comparison.

---

# Source verification ledger

| Provider | Source area | Verification date |
|---|---|---|
| AWS | ELB pricing, ALB/NLB LCU definitions and quotas | 2026-08-26 |
| Azure | Application Gateway v2 capacity, pricing model, metrics | 2026-08-26 |
| Google Cloud | Cloud Load Balancing pricing, proxy capacity, quotas | 2026-08-26 |
| DigitalOcean | Regional/Global LB pricing, limits, scaling, metrics | 2026-08-26 |
| OCI | Flexible LB shape docs and global price list | 2026-08-26 |
| Akamai | NodeBalancer specifications, price and metrics | 2026-08-26 |
| Hetzner | LB performance FAQ, product page and traffic limits | 2026-08-26 |
| Vultr | LB docs, pricing and bandwidth behavior | 2026-08-26 |


