# P014 route-error-threshold production A/B — 2026-09-16

## Scope

This was a single-variable production A/B on the accepted P009 coordinator and P013 5/60 concentrator profile. Only `CONCENTRATOR_ROUTE_ERROR_THRESHOLD` changed from `3` to `1`; RAM type stayed `high`, min/max stayed `5/60`, delivery-failure threshold stayed `1`, and channel/network identity/firmware resource tables were unchanged.

The test used ordinary Zigbee traffic only. No Mgmt_Rtg, Mgmt_Lqi, network-map, bulk-read, pairing, or stress traffic was generated. The threshold-1 candidate was proven active from the Zigbee2MQTT startup line before evidence collection.

## Primary predefined window

Equal adjacent windows of 19m56s were compared after excluding the restart/startup period.

| metric | threshold 3 | threshold 1 |
| --- | ---: | ---: |
| route errors | 12 | 12 |
| route errors/hour | 36.120 | 36.120 |
| burst-event excess | 2 | 1 |
| soft failures | 2 | 0 |
| hard coordinator/NCP failures | 0 | 0 |

Verdict from `deploy/analyze_route_threshold_ab.py`: **NO_CLEAR_CHANGE**. The route-error rate did not improve, so the candidate did not satisfy the promotion rule despite lower burst excess and soft-failure counts in this short window.
## Mature matched window

Because the short window was inconclusive, the already-running candidate was observed longer without changing any other variable. Equal 34m09s windows were then compared.

| metric | threshold 3 | threshold 1 |
| --- | ---: | ---: |
| route errors | 18 | 24 |
| route errors/hour | 31.625 | 42.167 |
| many-to-one | 13 | 18 |
| source-route | 5 | 6 |
| burst-event excess | 6 | 6 |
| soft failures | 4 | 4 |
| hard coordinator/NCP failures | 0 | 0 |

Threshold 1 increased route-error rate by **33.3%** (`+10.542/hour`) with no burst, soft-failure, or hard-failure benefit. The analyzer verdict is **WORSE_ROUTING**.

Candidate failures concentrated on live routers including `KitchenSocketFridge` (6), `HallBulb1` (5), `HallBreakerMain` (4), `KitchenSocketDishwasher` (3), and `HallBulb3` (3). NWK `56510` was unresolved in the current Zigbee2MQTT bridge/device inventory and is treated as stale/unresolved rather than evidence of coordinator table exhaustion.
## NCP pressure discriminator

The contemporaneous NCP counter snapshot showed zero ASH overflow/framing/overrun, packet-buffer allocation failure, PHY-to-MAC queue-limit hit, NWK retry overflow, broadcast-table-full, and address-conflict counters. The non-zero pressure signal was `PHY_CCA_FAIL_COUNT=341`.

Traffic context decoded from the same counter vector was 8,779 MAC broadcasts, 1,615 unicast retries, and 262 failed unicasts, with approximately 20.2 CCA failures per 1,000 TX-attempt events. This does not support another speculative route/source-route table, retry-queue, packet-buffer, or heap increase.

## Disposition

Threshold 1 is rejected. Production was restored from `/config/zigbee2mqtt/stack_config.json.pre-threshold1-20260916-201959` and restarted once. Startup at 20:57:52 CEST proved the accepted profile active again: high-RAM, 5/60, route-error threshold 3, delivery-failure threshold 1, EmberZNet 9.1.1 / EZSP19, with source-route discovery starting normally.

Keep threshold 3. Focus subsequent routing investigation on the small set of repeatedly implicated routers/end devices and RF/CCA conditions. Do not enlarge NCP resource tables without a matching counter signature.

Machine-readable reports:
- `evidence/P014_THRESHOLD_AB_20M_20260916.json`
- `evidence/P014_THRESHOLD_AB_34M_20260916.json`
