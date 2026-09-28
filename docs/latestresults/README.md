# Octavia Flavor Campaign Comparison

## At a glance

This report combines independently executed baseline-suite runs from the same `results/` tree. The report uses the latest **3** successful runs per flavor/scenario/path/topology group.

- Octavia flavors compared: **4** (lb.elite_experimental, lb.pro_experimental, lb.plus_experimental, lb.lite_experimental)
- Comparable scenario/path/topology populations: **4**
- Selected Octavia run samples: **48**
- Populations with multiple comparison fingerprints: **4**

### Simple scorecard

`Performance index` normalizes the primary throughput/capacity metric inside each scenario so the best flavor is 100. It is then summarized across scenarios using the median. This is a comparative index, **not** a synthetic requests-per-second number. `Latency index` similarly gives 100 to the lowest p99 latency within a scenario. Higher is better for both indexes. Lower run CV is more consistent.

| Flavor | Scenario wins | Coverage | Median performance index | Median latency index | Median run CV | Median failure % |
| --- | --- | --- | --- | --- | --- | --- |
| lb.elite_experimental | 4 | 4 | 100.0% | 100.0% | 4.6% | 0.000% |
| lb.pro_experimental | 0 | 4 | 58.3% | 58.4% | 3.6% | 0.000% |
| lb.plus_experimental | 0 | 4 | 16.9% | 18.7% | 3.5% | 0.068% |
| lb.lite_experimental | 0 | 4 | 15.2% | 15.7% | 2.9% | 0.047% |


## Charts

### Composite dashboard

This is the single-image overview intended for quick review, sharing, or presentation use. It combines overall flavor performance, scenario wins, per-scenario performance and p99 latency indexes, run variability, and flavor-scoped direct-nginx efficiency where available.

![Composite dashboard](charts/composite-dashboard.png)

### Individual charts

![Overall performance index](charts/flavor-overall-performance-index.png)

![Scenario performance matrix](charts/scenario-performance-index.png)

![Scenario p99 latency matrix](charts/scenario-latency-index.png)

![Scenario wins](charts/scenario-wins.png)

![Run-to-run variability](charts/flavor-variability.png)

## Reading this report

- Use **scenario wins** and the performance heatmap to see where each flavor is strongest.
- Use the **median performance index** for a compact cross-scenario view, but use the detailed tables for purchasing/product decisions because scenarios have different units and workload semantics.
- Use **run CV** to spot noisy or unstable results. With only three repetitions, treat very small differences as directional rather than statistically definitive.
- Any fingerprint warning means the harness detected comparison-critical configuration/software drift. Review those populations before drawing conclusions.

See [`DETAILED_COMPARISON.md`](DETAILED_COMPARISON.md) for actual metric values, ranges, p99 latency, failure rates, deltas, and direct-nginx references.

## Winner by scenario

| Scenario | Winner | Winning value | Unit | Runner-up | Margin |
| --- | --- | --- | --- | --- | --- |
| http_1k_keepalive | lb.elite_experimental | 93,181 | requests/s | lb.pro_experimental | 62.6% |
| tls_passthrough_1k_keepalive | lb.elite_experimental | 140,975 | requests/s | lb.pro_experimental | 93.7% |
| tls_termination_1k_keepalive | lb.elite_experimental | 73,892 | requests/s | lb.pro_experimental | 81.2% |
| tls_termination_reencrypt_1k_keepalive | lb.elite_experimental | 64,592 | requests/s | lb.pro_experimental | 35.6% |
