# MG24 tuning research after the stock BUSY investigation

This document separates **observed production evidence**, **linked/build evidence**, **stock-host runtime behavior**, and **future candidates**. Its purpose is to prevent the firmware from becoming a bundle of unrelated “large network” settings while also avoiding unnecessary measurement work for changes whose downside is negligible.

## 1. Production evidence

The retained production evidence is stronger than Permit Join alone:

- network-wide Permit Join reproduced intermittent BUSY;
- coordinator-only Permit Join controls remained clean;
- settled stock operation contained real user-facing group-send BUSY;
- the same basic failure class survived the older P007 host retry approach;
- retained settled ASH error counters were clean, although hourly sampling does not prove that host/transport queueing never contributes.

Concrete retained ordinary group failures included:

```text
Kitchen Table Bulbs               group 25
Sockets Nonessential Shutdown     group 31
Lights All                        group 8
```

Best-supported high-level path:

```text
coordinator-only permit       -> no network broadcast -> clean
Permit Join All               -> network broadcast(s) -> intermittent BUSY
ordinary group sends          -> multicast/broadcast admission -> same BUSY class
```

This keeps NCP network/send admission pressure as the leading branch. It does **not** prove that every BUSY was specifically `BROADCAST_TABLE_FULL`.

Credible alternatives/companions remain:

- local `NEW_BROADCAST_ENTRY_THRESHOLD` rejection;
- shared packet-buffer pressure;
- PHY-to-MAC queue pressure;
- NWK retry congestion;
- callback/host transport backlog;
- route/concentrator background work;
- RF contention extending the lifetime of queued work.

## 2. P009 profile

P009 changes exactly three values:

| Resource | Stock | P009 | Decision |
|---|---:|---:|---|
| EUSART RX buffer | 128 | **512** | keep |
| Broadcast table | 30 | **64** | primary intervention |
| Key table | 1 | **12** | keep |
| Multicast table | 26 | **26** | intentionally unchanged; 26 -> 32 is P013 only |

Retained values:

| Resource | P009 | Current decision |
|---|---:|---|
| Neighbor table | 26 | hard max; hold |
| Route table | 254 | hold |
| Source-route table | 254 | hold |
| Address table | 128 | hold |
| APS unicast messages | 128 | hold |
| Discovery table | 16 | hold |
| Binding table | 32 | hold |
| APS duplicate rejection | 64 | hold |
| Compiled max direct children | 64 | host normally requests 32 |
| Retry queue | 16 | hold |
| Packet-buffer heap profile | HUGE | do not infer free bytes from linker reservation |

## 3. Effective runtime configuration matters

The architecture review traced the pinned stock zigbee-herdsman 10.9.1 initialization path.

Important outcomes:

- stock herdsman does **not** rewrite BTT64 downward;
- stock herdsman does **not** rewrite KEY12 downward;
- multicast capacity is firmware-side; herdsman consumes memberships but does not resize the table;
- it normally attempts `MAX_END_DEVICE_CHILDREN=32` unless `stack_config.json` changes it;
- route/source-route table capacities remain firmware-side capacities while concentrator behavior is configured separately;
- `NEW_BROADCAST_ENTRY_THRESHOLD` is a distinct runtime admission control and its stock effective value is not yet proven by our deployment tooling;
- the optional six-value P009 policy therefore changes behavior rather than merely “making the compile-time firmware effective”.

Do not deploy threshold48 merely because BTT64 exists. Threshold changes admission behavior and have more downside than adding six multicast slots.

## 4. Actual linked memory cost

The architecture review independently parsed the matched stock/P009 ELF files. The frozen three-delta P009 image measured:

```text
                                  stock        old P009   delta
.text excluding RAM code         263,400     263,496       +96 B
.data                               4,600       4,600         0 B
.bss proper                        22,284      22,988      +704 B
.stack                              4,096       4,096         0 B
.noinit                               160         160         0 B
.memory_manager_heap reservation 229,896     229,896         0 B
```

The frozen P009 linked contract therefore remains:

```text
.bss proper                       22,284      22,988      +704 B
.memory_manager_heap reservation 229,896     229,896         0 B
```

The expected +704 B `.bss` delta is the linked result of RX512, BTT64 and KEY12. Multicast storage remains 104 B / 26 entries in both stock and P009. The separate P013 experiment changes multicast 26 -> 32 and adds another 24 B (`22,988 -> 23,012 B`) without being part of the first production P009 test.

For frozen P009:

```text
broadcast array stock: 240 B / 30 entries
broadcast array P009:  512 B / 64 entries
multicast array stock: 104 B / 26 entries
multicast array P009:  104 B / 26 entries
```

CI verifies these exact linked sizes on the fresh build. If alignment or generated code changes unexpectedly, the artifact fails rather than requiring a separate Home Assistant evidence campaign.

The memory-manager reservation remains 229,896 B. That is a linker reservation, not a measurement of free Zigbee packet memory after startup.

## 5. RX512

RX512 is already part of P009; it is not a future P010 candidate.

At 115200 baud, 8N1 nominal line rate is 11,520 B/s:

```text
128 B ~= 11.1 ms of line-rate storage
512 B ~= 44.4 ms
```

This adds roughly 33 ms of short-burst tolerance. It does not increase sustained throughput and does not address NCP-to-host callback pressure or ESP-bridge buffering by itself.

Keep SONOFF's EUSART1/115200/no-HW-flow contract unless end-to-end board/ESP support is proven.

## 6. Multicast membership: isolated as P013

The multicast table is not the number of groups the coordinator can transmit to. It is used for coordinator memberships/receive behavior.

Pinned herdsman has fixed multicast memberships and adds application group memberships dynamically. With roughly 21 configured groups, a 26-entry table may have limited theoretical margin, but changing it in P009 would confound the first causal BUSY test. Frozen P009 therefore remains at **26**. P013 is the isolated 26 -> 32 experiment and costs only +24 B linked `.bss`.

This is the model to use for future tuning decisions:

```text
small static-memory cost + useful headroom + no meaningful behavioral downside
    -> take the improvement and let CI verify the binary

behavioral/routing/admission change or meaningful RAM cost
    -> require stronger evidence first
```

## 7. Counter diagnostics

Relevant existing Ember counters:

```text
ASH_OVERFLOW_ERROR
ASH_FRAMING_ERROR
ASH_OVERRUN_ERROR
ALLOCATE_PACKET_BUFFER_FAILURE
PHY_TO_MAC_QUEUE_LIMIT_REACHED
TYPE_NWK_RETRY_OVERFLOW
PHY_CCA_FAIL_COUNT
BROADCAST_TABLE_FULL
ADDRESS_CONFLICT_SENT
```

`BROADCAST_TABLE_FULL` is important evidence but must be interpreted carefully:

- an increase supports broadcast-table pressure somewhere in that observation epoch;
- it does not prove the locally failed command caused the increment;
- a zero delta does not necessarily exclude local-threshold rejection unless that exact SDK path is known to increment the counter.

Pinned herdsman clears its counter vector hourly. Any event-adjacent snapshot must record the owner session, time, clear/reset boundary, context and read latency.

P010 now schedules a single read-only counter snapshot asynchronously and coalesces repeated BUSY triggers for five seconds. It does not delay propagation of the original BUSY.

## 8. Routing evidence that should not be misused

A historical source-route storm was dominated by an operator diagnostic `/get` sweep against a stale NWK address. After the device rejoined with a new NWK address, the failures disappeared. This is not evidence for enlarging route/source-route tables beyond the already-large 254/254 capacities.

An earlier A/B changing `CONCENTRATOR_DELIVERY_FAILURE_THRESHOLD` from 1 to 3 was materially worse:

```text
baseline threshold1:
  MAC success/retry/fail 1645/1215/189
  APS 1460/68
  route discoveries 155
  ZCL failures 2

threshold3:
  MAC success/retry/fail 1874/2150/419
  APS 1582/101
  route discoveries 180
  ZCL failures 12
```

Do not revive threshold3 without new evidence that invalidates that A/B.

Historical neighbor-table occupancy reached **26/26**. Twenty-six is the Silicon Labs hard maximum, so firmware cannot solve that by setting 27/32.

## 9. Ranked next candidates

### A — Acceptance/evidence correctness: mandatory before flash

- fresh current-owner identity rather than stale backup-file claims;
- current Docker startup epoch for version evidence;
- exact expected add-on owner;
- complete 16-result active canary;
- fail-fast Permit Join;
- correlated close + fresh `permit_join=false`;
- partial evidence persisted before STOP;
- exact linked binary/profile contract.

Implemented in `p009-hardening`; CI remains the gate.

### B — Identity-only XNCP: strong follow-up

A minimal custom extension should expose deterministic:

```text
schema version
project ID
board ID
firmware profile ID
source/build ID
canonical resource-profile hash
stack/EZSP cross-check
capability bitmap
```

Stock Zigbee2MQTT must remain able to ignore it. Do not copy Nabu Casa's entire behavior-changing extension merely for identity.

### C — Event-adjacent counter snapshot: strong diagnostic

Prepared as P010, now non-blocking/rate-limited. Use only after a residual BUSY.

### D — Multicast table 26→32: separate P013

Keep it isolated from the first P009 deployment. Its linked cost is only ~24 B, so P013 remains a cheap follow-up if membership headroom becomes relevant.

### E — Watchdog: conditional

First prove whether the generated firmware has one enabled, what feeds it, and how reset cause is surfaced. Do not enable a watchdog merely because resets are generally desirable.

### F — Scoped host pacing

For HA-originated bulk groups only, avoid unnecessary concurrent broadcast bursts. Approximate 1 s spacing, or ~2 s for large independent shutdown groups, is an operating policy to validate—not a Zigbee requirement. Do not throttle direct-bound buttons or reorder non-idempotent commands.

## 10. Rejected without new evidence

Do not introduce:

- BTT254;
- blanket BUSY retry loops;
- larger retry queue without retry-overflow evidence;
- higher RF power as a generic fix;
- ZBT-2 460800/CTS-RTS transport copied to SONOFF;
- route/source-route growth beyond 254;
- unsupported neighbor sizes;
- forced runtime child64 without direct-child pressure;
- threshold48 solely because it sounds like useful reserve;
- “max everything” resource profiles;
- bundled security-storage migration;
- persistent NVM writes per BUSY/counter event;
- unsolicited raw packet/health streaming.

## 11. Decision tree after hardened P009

```text
bounded P009 acceptance passes
    -> accept operationally; stop testing

residual BUSY
    -> preserve exact call path + current session + counter epoch

BROADCAST_TABLE_FULL rises
    -> establish BTT + local threshold + host pacing
    -> only then consider a modest single-variable BTT experiment

ALLOCATE_PACKET_BUFFER_FAILURE rises
    -> inspect packet-pool acquisition/low-water/fragmentation

PHY_TO_MAC_QUEUE_LIMIT_REACHED rises
    -> inspect MAC scheduling and callback/traffic bursts

NWK_RETRY_OVERFLOW rises
    -> inspect retry source / routing; do not automatically enlarge queue

PHY_CCA_FAIL_COUNT dominates without BTT pressure
    -> RF/channel/interference branch

ASH_* / host transport evidence rises
    -> transport/ESP/UART branch

no discriminator moves
    -> mechanism unresolved; inspect exact status path or isolated trace
```

The objective is not the largest possible tables. It is a coordinator whose limits are explicit, whose low-risk headroom is sensible, and whose higher-risk changes remain attributable and reversible.
