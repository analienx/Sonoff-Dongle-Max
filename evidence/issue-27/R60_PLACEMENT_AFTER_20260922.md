# Issue #27 — relocated SONOFF A/B result, 2026-09-22

Canonical task: [#27](https://github.com/analienx/Sonoff-Dongle-Max/issues/27); R60 baseline [#19](https://github.com/analienx/Sonoff-Dongle-Max/issues/19); reliability epic [#18](https://github.com/analienx/Sonoff-Dongle-Max/issues/18). User confirmed whole-dongle relocation away from original ~10 cm Pi/USB3-SSD placement. Physical separation, antenna orientation and local interference were not instrument-measured; Zigbee channel, TX power, firmware, pairing and device-power configuration were not intentionally changed.

## Identical powered-device cohort, bounded NCP windows

| Measurement | Original A | Moved B (valid retry) | Moved B repeat |
|---|---:|---:|---:|
| Captured UTC | Baseline earlier on 2026-09-22 | 15:15:29–15:20:29 | 15:21:39–15:26:39 |
| Duration (s) | 299.4 | 300.0 | 299.9 |
| Verified endpoint ZCL reads | 33/33, 11 routers | 33/33, same 11 | 33/33, same 11 |
| MAC unicast failed / successful | 82 / 694 | 99 / 704 | 121 / 653 |
| MAC failure fraction | 10.567% | 12.329% | 15.633% |
| MAC unicast retries | 426 | 474 | 597 |
| PHY clear-channel-assessment failures | 47 | 105 | 81 |
| Neighbor additions / removals | 31 / 31 | 38 / 38 | 44 / 44 |
| Combined neighbor changes/min | 12.426 | 15.198 | 17.606 |
| Distinct direct neighbors departed / arrived | 5 / 5 | 3 / 3 | 5 / 5 |
| APS unicast failures / route discoveries | 4 / 11 | 24 / 31 | 4 / 9 |
| Direct neighbors first/last | 26/26, 26/26 | 26/26, 26/26 | 26/26, 26/26 |
| Source-route entries first→last | 81→81 | 82→83 | 83→83 |

The first **moved B attempt** ran 15:07:37–15:12:37 UTC and achieved 33/33 verified ZCL reads, but ten NCP counters decreased synchronously (including MAC success 6563→52), consistent with a scheduled hourly counter clear; **its RF delta is invalid and is not used in this table**. Both the original invalid capture and its three raw one-shot files are retained privately. The retry is stored separately; no baseline or rejected result was overwritten.

## Integrity, interpretation and next action

The three valid windows had identical device cohorts, one unchanged Zigbee2MQTT owner epoch, verified extension removal after every one-shot, counter-clear audit `status=ok`/zero markers, and comparable MAC frame counts (776/803/774). No packet-buffer, broadcast-table, PHY-to-MAC queue, NWK retry-queue or ASH error event was recorded in these deltas. All 99 sampled ZCL reads succeeded, but ordinary household group commands, unsampled multi-hop paths and long-term reliability were **not** proven. One router's median read latency was 128 ms → 1062 ms → 95 ms, a transient rather than persistent paired failure. Cached first-hop route and per-window median LQI must not be treated as on-air causal traces.

**Finding:** Moving the dongle has not demonstrated improved MAC delivery or neighbor stability in these matched short windows. Two independent moved-position windows had greater MAC failure fractions and neighbor churn than the single original-position baseline. This neither isolates USB3 EMI nor proves the new position inherently worse; RF loading, antenna geometry and temporal variation remain confounders. No firmware or network setting should be changed on this experiment's evidence alone. Continue root-cause isolation under #19/#18 with bounded link/RF diagnostics and actual end-to-end command outcomes, rather than reopening the completed A baseline.

**Private, not in Git:** `C:\Workspace\.analienx\sonoff-private\issues\27-placement\r60_placement_v2_{before,after,after_retry1,confirm}.json` plus referenced raw coordinator/ZCL captures. Historical raw captures are retained in the authorized host spool; never commit IEEE/NWK mappings, secrets or raw HA logs.
