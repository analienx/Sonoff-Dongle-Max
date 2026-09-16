# P013 concentrator A/B — 2026-09-16

## Scope

Production Zigbee2MQTT quiet-traffic comparison of Ember concentrator timing only. No Mgmt_Rtg, Mgmt_Lqi, network-map, re-pair, channel, PAN, key, coordinator identity, firmware table-size, or TX-power changes were made.

Common runtime profile in both samples:
- `CONCENTRATOR_RAM_TYPE=high`
- `CONCENTRATOR_ROUTE_ERROR_THRESHOLD=3`
- `CONCENTRATOR_DELIVERY_FAILURE_THRESHOLD=1`
- `CONCENTRATOR_MAX_HOPS=0`
- `MAX_END_DEVICE_CHILDREN=32`

Compared profiles:
- baseline: `MIN_TIME=5`, `MAX_TIME=60`
- candidate: `MIN_TIME=10`, `MAX_TIME=120`

Each sample was trimmed to an equal 24m48s ordinary-traffic window after its profile restart.
## Result

| Metric | 5/60 baseline | 10/120 candidate |
|---|---:|---:|
| route errors | 2 | 3 |
| route-error rate | 4.84/h | 7.26/h |
| soft failures | 14 | 13 |
| soft-failure rate | 33.87/h | 31.45/h |
| address conflicts | 0 | 0 |
| APS no-ack | 0 | 0 |
| MAC no-ack | 0 | 0 |
| ASH transport | 0 | 0 |
| network down | 0 | 0 |
| packet-buffer / retry-overflow | 0 | 0 |
| management-scan markers | 0 | 0 |

Both windows contain one symmetric restart/NCP-reset marker at their beginning; it is not evidence that either timing profile caused a production reset.

`analyze_concentrator_ab.py` verdict: **WORSE_ROUTING** for 10/120, because route-error rate increased by more than 20% while the small soft-failure improvement did not offset the routing regression.
## Decision

Keep production at **High-RAM 5/60, thresholds 3/1**.

The 10/120 candidate is rejected. Current evidence does not justify increasing routing/source-route table sizes or changing coordinator firmware resources: P009 already has ample table capacity, and the bounded runtime-timing experiment shows no benefit from the slower 10/120 concentrator cadence.

P013 remains open for residual real-world address-conflict/no-ack evidence. Future coordinator changes must be tied to a reproduced hard signature or counter/resource evidence rather than speculative capacity increases.