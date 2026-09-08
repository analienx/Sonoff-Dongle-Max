# SONOFF Dongle-M MG24 resource profiles

Target: SONOFF Dongle-M / Dongle Max, `EFR32MG24A420F1536IM48`.

Pinned builder: `Nerivec/silabs-firmware-builder@858c34b0eb6f53a2e0c89455ea489ceaa62d58db`

Pinned stack/toolchain generation: Simplicity SDK 2026.6.1, EmberZNet 9.1.1, EZSP 19, GCC 14.2.1.

## Frozen P009 production candidate

P009 is permanently the original three-delta profile. Exactly three values differ from the matched stock rollback:

```text
SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE 128 -> 512
SL_ZIGBEE_BROADCAST_TABLE_SIZE         30 -> 64
SL_ZIGBEE_KEY_TABLE_SIZE                1 -> 12
```

Multicast remains **26** in P009. A multicast32 image is P013, not P009.

The broadcast table is the primary intervention for the observed group/broadcast `SLStatus.BUSY`. RX512 adds short-burst host→NCP buffering. KEY12 adds APS/link-key storage without changing network security material.

## Retained P009 compile-time profile

```text
SL_ZIGBEE_MULTICAST_TABLE_SIZE                  26
SL_ZIGBEE_ROUTE_TABLE_SIZE                     254
SL_ZIGBEE_SOURCE_ROUTE_TABLE_SIZE              254
SL_ZIGBEE_ADDRESS_TABLE_SIZE                   128
SL_ZIGBEE_APS_UNICAST_MESSAGE_COUNT            128
SL_ZIGBEE_DISCOVERY_TABLE_SIZE                  16
SL_ZIGBEE_NEIGHBOR_TABLE_SIZE                  26
SL_ZIGBEE_BINDING_TABLE_SIZE                   32
SL_ZIGBEE_MAX_END_DEVICE_CHILDREN              64
SL_ZIGBEE_APS_DUPLICATE_REJECTION_MAX_ENTRIES 64
SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE              HUGE
retry queue                                     16
```

`SL_ZIGBEE_NEIGHBOR_TABLE_SIZE=26` is already the Silicon Labs maximum for this stack family.

### Compile-time capacity versus host runtime policy

Do not conflate linked capacity with host-requested runtime values:

- direct-child capacity linked into the NCP: **64**;
- pinned stock zigbee-herdsman 10.9.1 normally attempts runtime `MAX_END_DEVICE_CHILDREN=32` unless `stack_config.json` overrides it;
- stock herdsman does not normally lower BTT64 or KEY12;
- multicast capacity is linked in firmware; herdsman consumes memberships but does not resize the table;
- `NEW_BROADCAST_ENTRY_THRESHOLD` is a separate admission-policy question.

The optional threshold48 runtime policy therefore must not be applied merely to “preserve” BTT64.

## P009 linked-image contract

For the pinned build generation:

```text
                                  stock        P009      delta
.bss proper                       22,284      22,988      +704 B
.memory_manager_heap reservation 229,896     229,896         0 B
```

Expected linked storage changes:

```text
rx_buffer_vcom                           128 -> 512 B   (+384)
sli_zigbee_broadcast_table_data          240 -> 512 B   (+272)
sli_zigbee_incoming_aps_frame_counters     8 ->  52 B    (+44)
sli_zigbee_multicast_table               104 -> 104 B      (0)
alignment/layout                                           (+4)
```

CI verifies exact section and symbol sizes against the freshly linked ELF. The unchanged 229,896-B `.memory_manager_heap` region is a **reservation**, not a measurement of free Zigbee packet memory after startup.

Other retained linked arrays include:

```text
retry queue                         320 B
source-route table data           1,016 B
route table                       2,040 B
child table                       1,560 B
```

For this stack generation the broadcast backing array is 8 B/entry and multicast membership storage is 4 B/entry. Use linked evidence rather than generic estimates.

## P013 — explicit multicast-headroom experiment

P013 is derived from frozen P009 and changes exactly one additional resource:

```text
SL_ZIGBEE_MULTICAST_TABLE_SIZE 26 -> 32
```

Expected linked contract:

```text
P009 .bss   22,988 B
P013 .bss   23,012 B
P013-P009      +24 B
```

The multicast table tracks coordinator receive memberships; it is not the broadcast transmit-admission queue. P013 exists because six extra memberships are cheap and potentially useful, but keeping it separate avoids polluting the first causal P009 BUSY experiment.

P013 is disabled by default and must never be relabelled as P009.

## P011 — identity-only XNCP on P009

P011 starts from frozen P009 and must preserve its Zigbee resource/transport profile exactly. It adds only a small XNCP identity surface.

Its canonical resource identity hashes a deterministic semantic profile containing project, board, stack, EZSP, transport and explicit resource values. The build-side identity record contains the full source SHA and full SHA-256. The wire response contains compact prefixes.

This is **operational self-identification**, not cryptographic remote attestation. Stock Zigbee2MQTT must continue working if it ignores XNCP.

CI measures P011 `.text/.data/.bss` delta against P009 and verifies linked XNCP callback symbols before the variant is accepted into the bundle.

## P012 — watchdog/reset research boundary

The pinned upstream `zigbee_ncp.slcp` does not explicitly select a watchdog component. P009/P011/P013 therefore do not silently add watchdog behavior.

P012 remains a required research/diagnostic bundle component whose production promotion is blocked on a controlled non-production hardware test proving reset cause, single recovery without reset loop and preserved network/NVM state. See `docs/P012-WATCHDOG-RESET.md`.

## Transport contract

```text
EUSART1
115200 baud
no hardware flow control
P009/P011/P013 RX buffer 512 B
stock rollback RX buffer 128 B
```

At 115200 8N1, 512 B is roughly 44 ms of nominal line-rate burst storage versus ~11 ms at 128 B. It does not raise sustained throughput.

Do not copy ZBT-2-specific 460800/CTS-RTS settings onto the SONOFF board without end-to-end proof across the ESP bridge, pins and firmware.

## Verification layers

Authoritative release CI separates:

1. stock/patched source-profile inputs;
2. generated component/configuration/build metadata;
3. linked ELF section/symbol evidence and executable assertions;
4. exact GBL/HEX/OUT hashes;
5. resolved CI toolchain/base-image provenance;
6. later live owner-bound Zigbee2MQTT/network evidence.

A source file is not called “effective configuration,” and a GBL hash acknowledgment is not called device-side attestation.
