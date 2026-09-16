# P014 route-error-threshold production A/B — 2026-09-16

## Scope

This was a single-variable production A/B on the accepted P009 coordinator and P013 5/60 concentrator profile. Only `CONCENTRATOR_ROUTE_ERROR_THRESHOLD` changed from `3` to `1`; RAM type stayed `high`, min/max stayed `5/60`, delivery-failure threshold stayed `1`, and channel/network identity/firmware resource tables were unchanged.

The test used ordinary Zigbee traffic only. No Mgmt_Rtg, Mgmt_Lqi, network-map, bulk-read, pairing, or stress traffic was generated. The threshold-1 candidate was proven active from the Zigbee2MQTT startup line before evidence collection.

## Primary predefined window

Equal adjacent windows of 19m56s were compared beginning after the explicit startup ping/configuration sequence had completed, but without an additional post-startup settling grace.

| metric | threshold 3 | threshold 1 |
| --- | ---: | ---: |
| route errors | 12 | 12 |
| route errors/hour | 36.120 | 36.120 |
| burst-event excess | 2 | 1 |
| soft failures | 2 | 0 |
| hard coordinator/NCP failures | 0 | 0 |

Verdict from `deploy/analyze_route_threshold_ab.py`: **NO_CLEAR_CHANGE**. The route-error rate did not improve, so the candidate did not satisfy the promotion rule.

## Longer raw matched window

The already-running candidate was observed longer without changing any other variable. A raw equal 34m09s comparison produced 18 route errors at threshold 3 versus 24 at threshold 1 (31.625/h vs 42.167/h). The analyzer labels that raw window `WORSE_ROUTING`.
That raw comparison is not used as the final causal claim because the candidate followed a Z2M restart while the baseline came from an already-settled session. Startup pings/configuration are known to generate transient routing work on this network.

## Steady-state correction

To remove the restart confound, the candidate was re-cut beginning five minutes after the last explicit startup recovery probe. Equal 29m29s steady-state windows were compared.

| metric | threshold 3 | threshold 1 |
| --- | ---: | ---: |
| route errors | 18 | 21 |
| route errors/hour | 36.589 | 42.736 |
| many-to-one | 13 | 15 |
| source-route | 5 | 6 |
| burst-event excess | 6 | 6 |
| soft failures | 4 | 4 |
| hard coordinator/NCP failures | 0 | 0 |

This is approximately a 16.8% higher route-error rate at threshold 1, but it does not cross the analyzer's >20% regression gate. Burst and soft-failure rates are effectively unchanged. Final steady-state verdict: **NO_CLEAR_CHANGE**.

The promotion criterion requires a clear improvement, not merely absence of a hard regression. Threshold 1 therefore remains rejected: it did not reduce steady-state route errors, bursts, or soft failures.

Repeated candidate targets remained concentrated on `KitchenSocketFridge`, `HallBulb1`, `HallBreakerMain`, `KitchenSocketDishwasher`, and `HallBulb3`, supporting targeted route/RF investigation rather than NCP-capacity expansion.
## NCP pressure discriminator

The contemporaneous NCP counter snapshot showed zero ASH overflow/framing/overrun, packet-buffer allocation failure, PHY-to-MAC queue-limit hit, NWK retry overflow, broadcast-table-full, and address-conflict counters. The non-zero pressure signal was `PHY_CCA_FAIL_COUNT=341`.

Traffic context decoded from the same counter vector was 8,779 MAC broadcasts, 1,615 unicast retries, and 262 failed unicasts, with approximately 20.2 CCA failures per 1,000 TX-attempt events. This does not support another speculative route/source-route table, retry-queue, packet-buffer, or heap increase.

## Disposition

Threshold 1 is rejected because it failed to demonstrate a steady-state routing improvement. Production was restored from `/config/zigbee2mqtt/stack_config.json.pre-threshold1-20260916-201959` and restarted once. Startup at 20:57:52 CEST proved the accepted profile active again: high-RAM, 5/60, route-error threshold 3, delivery-failure threshold 1, EmberZNet 9.1.1 / EZSP19, with source-route discovery starting normally.

Keep threshold 3. Focus subsequent routing investigation on the small set of repeatedly implicated routers/end devices and RF/CCA conditions. Do not enlarge NCP resource tables without a matching counter signature.

Machine-readable reports:
- `evidence/P014_THRESHOLD_AB_20M_20260916.json` — predefined window
- `evidence/P014_THRESHOLD_AB_34M_20260916.json` — raw longer window; restart-adjacent, not final causal verdict
- `evidence/P014_THRESHOLD_AB_STEADY_29M_20260916.json` — final steady-state comparison
