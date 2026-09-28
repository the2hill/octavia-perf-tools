# Detailed Octavia Flavor Comparison

Each table below is one comparable scenario/path/generator-topology population. The primary metric is chosen from the scenario semantics: max sustainable RPS for adaptive max-RPS tests, approximate connections/s for connection-churn tests, simultaneous connections for capacity tests, payload Gb/s for large-payload bandwidth tests, and peak RPS for ordinary keepalive tests.

## http_1k_keepalive

Traffic path: `tenant_vip`  
Generator topology: `shared`  
Primary metric: `peak_rps_history` (requests/s)

| Flavor | Runs | Median | Min | Max | Run CV | vs best | p99 ms | Failure % | Fingerprints |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lb.elite_experimental | 3 | 93,181 | 89,688 | 126,723 | 21.9% | 0.0% | 130.0 | 0.000% | 2 |
| lb.pro_experimental | 3 | 57,308 | 54,634 | 59,285 | 4.1% | -38.5% | 220.0 | 0.000% | 2 |
| lb.plus_experimental | 3 | 16,112 | 15,480 | 16,589 | 3.5% | -82.7% | 670.0 | 0.000% | 2 |
| lb.lite_experimental | 3 | 13,470 | 12,988 | 13,852 | 3.2% | -85.5% | 840.0 | 0.000% | 2 |

### Direct nginx control provenance

| Suite flavor | Runs | Median | Unit | Suite IDs |
| --- | --- | --- | --- | --- |
| legacy_unscoped | 2 | 88,233 | requests/s | 20260918T041925657389Z,20260918T050419148539Z |

**Legacy direct-control warning:** these older results predate suite-flavor provenance tagging. They are shown for context but are not used for flavor-specific Octavia-to-direct ratios.

**Compatibility warning:** one or more flavor groups contain multiple fingerprints. Review `selected-runs.csv` and the original `RUN_MANIFEST.md` files before treating this population as controlled.

## tls_passthrough_1k_keepalive

Traffic path: `tenant_vip`  
Generator topology: `shared`  
Primary metric: `peak_rps_history` (requests/s)

| Flavor | Runs | Median | Min | Max | Run CV | vs best | p99 ms | Failure % | Fingerprints |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lb.elite_experimental | 3 | 140,975 | 136,766 | 153,675 | 6.2% | 0.0% | 98.0 | 0.000% | 1 |
| lb.pro_experimental | 3 | 72,766 | 70,941 | 80,106 | 6.7% | -48.4% | 170.0 | 0.000% | 1 |
| lb.lite_experimental | 3 | 25,930 | 24,996 | 28,306 | 6.6% | -81.6% | 450.0 | 0.078% | 1 |
| lb.plus_experimental | 3 | 23,221 | 22,345 | 24,023 | 3.6% | -83.5% | 460.0 | 0.130% | 1 |

### Direct nginx control provenance

| Suite flavor | Runs | Median | Unit | Suite IDs |
| --- | --- | --- | --- | --- |
| legacy_unscoped | 2 | 71,987 | requests/s | 20260918T041925657389Z,20260918T050419148539Z |

**Legacy direct-control warning:** these older results predate suite-flavor provenance tagging. They are shown for context but are not used for flavor-specific Octavia-to-direct ratios.

## tls_termination_1k_keepalive

Traffic path: `tenant_vip`  
Generator topology: `shared`  
Primary metric: `peak_rps_history` (requests/s)

| Flavor | Runs | Median | Min | Max | Run CV | vs best | p99 ms | Failure % | Fingerprints |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lb.elite_experimental | 3 | 73,892 | 73,586 | 75,516 | 1.4% | 0.0% | 160.0 | 0.000% | 1 |
| lb.pro_experimental | 3 | 40,779 | 40,435 | 42,704 | 3.0% | -44.8% | 250.0 | 0.000% | 1 |
| lb.plus_experimental | 3 | 12,248 | 12,117 | 12,377 | 1.1% | -83.4% | 890.0 | 0.005% | 1 |
| lb.lite_experimental | 3 | 9,920 | 9,512 | 9,981 | 2.6% | -86.6% | 1,000 | 0.016% | 1 |

## tls_termination_reencrypt_1k_keepalive

Traffic path: `tenant_vip`  
Generator topology: `shared`  
Primary metric: `peak_rps_history` (requests/s)

| Flavor | Runs | Median | Min | Max | Run CV | vs best | p99 ms | Failure % | Fingerprints |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lb.elite_experimental | 3 | 64,592 | 62,504 | 66,387 | 3.0% | 0.0% | 180.0 | 0.002% | 1 |
| lb.pro_experimental | 3 | 47,634 | 45,145 | 47,899 | 3.2% | -26.3% | 320.0 | 11.162% | 1 |
| lb.plus_experimental | 3 | 14,323 | 13,640 | 14,677 | 3.7% | -77.8% | 10,000 | 43.463% | 1 |
| lb.lite_experimental | 3 | 10,330 | 10,227 | 10,689 | 2.3% | -84.0% | 10,000 | 38.456% | 1 |

## Selected source runs

The exact source directories used for this report are listed in `selected-runs.csv`. This makes the report reproducible even when older benchmark history remains under `results/`.

