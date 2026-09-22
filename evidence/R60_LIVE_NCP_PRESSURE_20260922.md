# R60 live NCP readback: neighbor churn and first-hop MAC failures — 2026-09-22

Parent #18, baseline #19, source PR #25. **Sanitized counters only; raw IEEE/NWK, source-route chains, MQTT credentials and original logs remain private on the authorized laptop.** No second serial owner, network-map scan, pairing, network/firmware/TX change, counter clearing, or induced link failure.

## Method, timing, and rollback

Pinned Zigbee2MQTT 2.14.0 / herdsman 10.9.1 existing Ember owner; owner `StartedAt=2026-09-22T06:12:05.582374526Z` stayed unchanged. The reviewed extension uses `adapter.queue.execute()` for **every EZSP read** (correction from the earlier neighbor-only diagnostic, which did not serialize through this queue). One 26-neighbor table read, source-route filled/total, 79 indexed source-route reads, and one **non-clearing** `ezspReadCounters()` read through the owner. Read-only EZSP methods; transient external-extension save/remove through hash-pinned typed helper in `analienx/config` draft PR #61. Latest private result timestamp **2026-09-22T11:22:31.729Z**. Result `ok`, one owner epoch, temp `.cjs` file verified absent after removal; Zigbee2MQTT-managed `external_extensions/node_modules` symlink may remain as before.

Read/clear epoch independently located from **targeted, filtered current-owner Docker output**: latest `[NCP COUNTERS]` hourly clear on **2026-09-22 13:12:09 Europe/Prague (11:12:09Z)**. That previous counter epoch reported neighbor added **349**, removed **349**, MAC failed unicast **910**. This is the previous clear-to-clear period, not equivalent to 910 end-user commands failing. The non-clearing read at 13:22:31 Prague is about **10 min 23 s after the latest clear**, so the current counters below are **since that clear**, barring asynchronous clear/reset not seen in the targeted recent log. The NCP counters use 16-bit unsigned values; no counter-wrap conclusion is needed for these observed values.

## Current non-clearing counter vector (about 10m23s since hourly clear)

| Counter | Value |
|---|---:|
| `MAC_TX_UNICAST_SUCCESS` | 1332 |
| `MAC_TX_UNICAST_RETRY` | 866 |
| **`MAC_TX_UNICAST_FAILED`** | **192** |
| `APS_DATA_TX_UNICAST_SUCCESS` | 1029 |
| `APS_DATA_TX_UNICAST_FAILED` | 0 |
| `ROUTE_DISCOVERY_INITIATED` | 13 |
| **`NEIGHBOR_ADDED` / `NEIGHBOR_REMOVED`** | **61 / 61** |
| `NEIGHBOR_STALE` | 35 |
| `PHY_CCA_FAIL_COUNT` | 99 |
| `BROADCAST_TABLE_FULL` | 0 |
| `ALLOCATE_PACKET_BUFFER_FAILURE` | 0 |
| `PHY_TO_MAC_QUEUE_LIMIT_REACHED` | 0 |
| `TYPE_NWK_RETRY_OVERFLOW` | 0 |
| `ASH_OVERFLOW_ERROR` / `ASH_FRAMING_ERROR` / `ASH_OVERRUN_ERROR` | 0 / 0 / 0 |
| `ADDRESS_CONFLICT_SENT` | 0 |

This is **active neighbor turnover** at a persistently occupied table, not a frozen admission/eviction algorithm. Distinguish neighbor turnover from true RF loss: `NEIGHBOR_STALE=35` is not a per-removal reason code. The nonzero `ROUTE_DISCOVERY_INITIATED=13` means some NWK route discoveries *were accepted for submission to the MAC* during this epoch; it does **not** enumerate individual on-air MTORR advertisements or prove that distant routers received them. The `MAC_TX_UNICAST_FAILED` event counts **link-layer transmissions**, not 192 ZCL failed commands: APS unicast failure counter is 0 in this same short epoch. No evidence here for NCP broadcast-table/packet-pool/ASH exhaustion. Older retained logs contain genuine failed `set` operations in other epochs.

## NCP table state

Neighbor table **26/26**; the previous outgoing-cost-0 neighbor was **not** present in this read (`0` neighbors with outbound cost 0). Source-route table **79/254**; all 79 indexed source-route entries have distinct destination short addresses. The NCP `closerIndex` chains have 30 direct, 34 one-relay, and 15 two-relay chains; all terminate with the expected `255` sentinel, none contain invalid indices or cycles. This establishes only structural consistency, **not** that every stored radio path works over the air or that a stale NWK/IEEE mapping is absent.

## Engineering decision

**Leading actionable fault class: sustained high-rate neighbor replacement plus first-hop MAC delivery loss on a dense direct-router population.** This is a more defensible first target than another MTORR timer, route-table 254 increase, forcing out one weak neighbor, indiscriminate TX change, or disabling source-route storage. A full 26-entry table with active replacement and 61 add/remove events in ~10 minutes is evidence for **capacity/selection pressure**, not proof that a hypothetical 60-neighbor firmware change can be built safely or will eliminate it. More radios or another link may be involved; Wi-Fi AP state, antenna/placement and radio interference remain unverified.

**One next intervention:** use one reversible, controlled physical/RF change at the coordinator (verify current SONOFF AP/WLAN mode on the wired device, disable an active 2.4GHz AP through its supported authenticated console if enabled, or relocate/separate its Zigbee antenna from colocated emitters without changing PAN/channel/IEEE), then compare short matched **MAC failure + neighbor turnover + actual ZCL command delivery** counters, not raw route errors alone. If RF separation cannot reduce turnover substantially, pursue vendor- or stack-supported neighbor selection/capacity remediation; do not claim that editing a constant or adding MTORR broadcasts is a fix. Preserve original configured TX 8 dBm at the capture; do not change it as part of the first intervention. Restore the original AP/placement if the short comparison worsens. This diagnostic did NOT deploy a reliability change.
