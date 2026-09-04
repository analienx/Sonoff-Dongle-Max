# MG24 tuning research after the stock BUSY investigation

This document separates **executor evidence**, **external/production-profile comparison**, and **future candidates**. It exists specifically to prevent P009 from turning into a bundle of unrelated parameter changes.

## 1. What the retained production logs actually establish

The old `home-assistant-stack#47` evidence is stronger than Permit Join alone:

- matched Permit-Join-All runs reproduced the same failure on stock herdsman 10.9.1 and the older P007 runtime;
- coordinator-only permit controls remained clean;
- settled stock operation contained real user-facing `ZCL GROUP ... status=BUSY` failures;
- all retained settled runs had zero ASH transport errors;
- the large `SOURCE_ROUTE_FAILURE` storm for NWK 24677 was strongly correlated with an operator diagnostic `/get` sweep and disappeared after that device rejoined with a new NWK address.

Concrete retained group failures:

```text
22:25:12 / 23:19:40  Kitchen Table Bulbs          group 25  BUSY
23:28:18              Sockets Nonessential Shutdown group 31 BUSY
23:28:22              Lights All                   group 8  BUSY
```

This makes the best-supported mechanism:

```text
coordinator-only permit       -> no network broadcast -> succeeds
Permit Join All               -> ZDO/GP broadcasts -> intermittent BUSY
ordinary Z2M group commands   -> multicast/broadcast path -> same BUSY
ASH transport                 -> clean
```

The first firmware intervention therefore remains broadcast/NWK admission headroom, not serial, routing or RF tuning.

## 2. Current resource comparison

| Resource | Nerivec MG24 stock | P009 | Current Nabu Casa ZBT-2 MG24 | Decision |
|---|---:|---:|---:|---|
| Broadcast table | 30 | **64** | **64** | P009 primary change |
| Key table | 1 | **12** | **12** | keep P009 |
| Neighbor table | 26 | 26 | 26 | hard max; no change |
| Route table | 254 | 254 | 254 | effectively max |
| Source-route table | 254 | 254 | 254 | effectively max |
| Address table | 128 | 128 | 128 | no evidence to raise |
| APS unicast messages | 128 | 128 | 128 | no evidence to raise |
| Discovery table | 16 | 16 | 16 | no evidence to raise |
| Multicast table | 26 | 26 | 26 | membership capacity, not send queue |
| APS duplicate rejection | 64 | 64 | 64 | keep |
| Packet-buffer heap | HUGE | HUGE | HUGE | keep |
| Max end-device children | 64 | 64 | 32 | our value is already larger |
| Child table | implicit 64 | implicit 64 | explicit 32 | no hidden bottleneck |
| EUSART RX buffer | 128 | 128 | **512** | P010 robustness candidate |
| UART | 115200/no-flow | same | 460800/CTS-RTS | hardware-specific; do not copy |

`SL_ZIGBEE_CHILD_TABLE_SIZE` defaults to `SL_ZIGBEE_MAX_END_DEVICE_CHILDREN`, so the Nerivec/P009 build's explicit max-children value of 64 also yields an effective child table of 64. There is no missing 32-entry child-table override to fix.

## 3. P009 binary cost

First successful dedicated-repo CI build:

```text
                         stock       P009       delta
ELF text                 264044      264140      +96 B
ELF data                   4612        4612        0 B
ELF bss                  289208      289528     +320 B
GBL bytes                268896      268992      +96 B
```

The MG24 memory-manager heap fills the remaining SRAM. P009's static cost is therefore very small.

Historic/current Silicon documentation describes a broadcast-table entry as 6 bytes. Memory is not the reason to stop at 64: EZSP permits a broadcast table up to 254. The reason to stop at 64 is **network behavior and production precedent**. Silicon warns that a node able to originate far more broadcasts than neighbors can track can overwhelm those neighbors; current Nabu Casa MG24 firmware independently uses 64. P009 should validate 64 before considering anything larger.

## 4. Ranked follow-up candidates

### A — Immediate NCP pressure observability: HIGH VALUE

Pinned herdsman 10.9.1 already does this once per hour:

```text
ezspReadAndClearCounters()
logger.info("[NCP COUNTERS] ...")
```

It also exposes read-only `ezspReadCounters()`.

Relevant Ember counters include:

```text
18 ASH_OVERFLOW_ERROR
19 ASH_FRAMING_ERROR
20 ASH_OVERRUN_ERROR
27 ALLOCATE_PACKET_BUFFER_FAILURE
29 PHY_TO_MAC_QUEUE_LIMIT_REACHED
31 TYPE_NWK_RETRY_OVERFLOW
32 PHY_CCA_FAIL_COUNT
33 BROADCAST_TABLE_FULL
40 ADDRESS_CONFLICT_SENT
```

`BROADCAST_TABLE_FULL` is the most important discriminator: it increments when a NWK broadcast is dropped because the broadcast table is full.

Repository tool: `deploy/decode_ncp_counters.py` decodes already-retained hourly vectors without touching the coordinator.

Future optional diagnostic overlay should perform a **read-only** counter snapshot immediately after a BUSY from ZDO broadcast, ZCL broadcast, or ZCL group. It must be best-effort only: no counter clear, no retry, no route change, and diagnostic failure must never mask the original send error.

### B — EUSART RX buffer 128 -> 512: GOOD P010 ROBUSTNESS CANDIDATE

Current Nabu Casa MG24 ZBT-2 firmware uses a 512-byte EUSART RX buffer versus 128 in the pinned Nerivec project.

Estimated extra static SRAM cost:

```text
512 - 128 = 384 bytes
```

That is tiny on this MG24 build. It could make the NCP more tolerant of short host/serial bursts. However, the executor evidence reports zero ASH errors and the decisive failures are returned by Network/MAC send admission, so RX512 is **not** a justified part of the BUSY fix. Keep it as a separately testable P010 variant.

### C — Broadcast table >64: TECHNICALLY POSSIBLE, NOT CURRENTLY JUSTIFIED

EZSP documents a maximum of 254 entries. Do not use that maximum as a target.

Move beyond 64 only if all of the following are true:

1. P009 still produces real group/broadcast BUSY;
2. an immediate/nearby counter snapshot shows `BROADCAST_TABLE_FULL` increasing;
3. HA-side burst pacing is already sane;
4. a larger value is tested as a single-variable image.

Even then, prefer a modest next step rather than 254 because neighboring routers have their own broadcast-table limits.

### D — Runtime `NEW_BROADCAST_ENTRY_THRESHOLD`: CONDITIONAL

Silicon defines the threshold as the maximum locally-originated broadcast entries before new local broadcasts are rejected. The difference

```text
BROADCAST_TABLE_SIZE - NEW_BROADCAST_ENTRY_THRESHOLD
```

is reserved for relaying broadcasts originated by other devices.

The prepared optional policy uses:

```text
BROADCAST_TABLE_SIZE          64
NEW_BROADCAST_ENTRY_THRESHOLD 48
```

which reserves 16 entries for relaying. Keep this policy separate from the firmware-first test until actual readback proves what stock herdsman/NCP initialization does with the enlarged compile-time table.

## 5. Parameters that should remain untouched without a matching error/counter

### Neighbor table — 26

26 is the Silicon Labs maximum. Nothing to improve.

### Route/source-route — 254/254

Already at the useful limit. The 24677 storm was predominantly caller-amplified stale route state and healed on rejoin/NWK change; it is not evidence that these tables were too small.

### APS unicast message count — 128

Already very large. Exhaustion has a specific `ZIGBEE_MAX_MESSAGE_LIMIT_REACHED` failure signature, which is not the decisive group/broadcast BUSY signature.

### Discovery table — 16

A discovery table controls simultaneous route discoveries. Current Nabu Casa MG24 also uses 16. Increase only if future evidence shows actual route-discovery saturation.

### Address table — 128

This is EUI64-to-NWK association capacity for the application, not simply 'one row per joined device'. Current Nabu Casa MG24 also uses 128 and the logs do not show address-table exhaustion.

### Multicast table — 26

This controls groups **the coordinator itself is a member of**, not the number of group-cast messages it can originate. Twenty-one Z2M groups do not imply this table is near exhaustion.

### Retry queue — 16

Do not enlarge without `TYPE_NWK_RETRY_OVERFLOW`. More retry capacity can prolong pressure rather than remove it.

### Baud/RTS-CTS

Keep Dongle-M at its documented `115200`, `rtscts:false` profile. The ZBT-2 460800/CTS-RTS configuration is tied to different hardware plumbing and should not be copied to Dongle-M.

### RF power / CCA / channel

No retained evidence points to them as the BUSY root cause. `PHY_CCA_FAIL_COUNT` gives us an evidence path if RF contention later becomes relevant.

## 6. Host-side complement that still makes sense

P009 should not be used as permission to blast more broadcasts. For coordinator-originated bulk HA actions:

```text
minimum ~1 s spacing between unrelated group/broadcast commands
prefer ~2 s for large independent all-off/shutdown groups
```

Critical OFF actions should use group-cast first, then reconcile individual devices by unicast only where actual state remains wrong. Direct-bound button traffic is not subject to this artificial pacing.

## 7. Decision tree after P009

```text
P009 acceptance passes
    -> accept P009; stop tuning

residual BUSY + BROADCAST_TABLE_FULL rises
    -> verify threshold/readback + HA burst pacing
    -> only then consider a modest BTT >64 experiment

residual BUSY + NWK_RETRY_OVERFLOW rises
    -> investigate retry/traffic source; do NOT automatically enlarge queue

residual BUSY + ALLOCATE_PACKET_BUFFER_FAILURE rises
    -> packet-buffer/heap pressure investigation

residual BUSY + PHY_TO_MAC_QUEUE_LIMIT_REACHED rises
    -> MAC scheduling/queue pressure investigation

high PHY_CCA_FAIL_COUNT without BTT pressure
    -> RF/channel/interference branch

ASH_* counters/errors rise
    -> transport branch; RX512 becomes materially justified

none of the above rises
    -> inspect exact status/call path before changing any firmware resource
```

The objective is not to maximize every table. It is to make the Dongle-M more tolerant where this production network demonstrably needs headroom while preserving enough observability to know when a different subsystem is actually the bottleneck.
