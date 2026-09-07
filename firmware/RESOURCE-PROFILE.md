# P009 MG24 resource profile

Target: SONOFF Dongle-M / Dongle Max, `EFR32MG24A420F1536IM48`.

Pinned builder: `Nerivec/silabs-firmware-builder@858c34b0eb6f53a2e0c89455ea489ceaa62d58db`

Pinned stack/toolchain generation: Simplicity SDK 2026.6.1, EmberZNet 9.1.1, EZSP 19, GCC 14.2.1.

## Intentional P009 compile-time deltas

Exactly four values differ from the matched stock rollback source profile:

```text
SL_IOSTREAM_EUSART_VCOM_RX_BUFFER_SIZE 128 -> 512
SL_ZIGBEE_BROADCAST_TABLE_SIZE         30 -> 64
SL_ZIGBEE_KEY_TABLE_SIZE                1 -> 12
SL_ZIGBEE_MULTICAST_TABLE_SIZE         26 -> 32
```

The broadcast table is the primary intervention for the observed group/broadcast `BUSY`. RX512 is short-burst transport robustness. KEY12 increases APS/link-key storage without changing the network security material. Multicast32 adds six receive-membership slots at only 24 B of linked static storage; it is included as low-cost headroom rather than waiting for a production registration failure.

## Retained compile-time profile

```text
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

## Compile-time capacity versus stock-host runtime policy

Do not conflate the linked maximum with the value the host asks the NCP to use:

- physical/direct-child capacity linked in the NCP: **64**;
- pinned stock zigbee-herdsman 10.9.1 normally attempts runtime `MAX_END_DEVICE_CHILDREN=32` unless `stack_config.json` overrides it;
- stock herdsman does **not** lower BTT64 or KEY12 in its normal startup path;
- multicast table capacity is linked in the NCP; herdsman consumes memberships but does not resize the table;
- effective `NEW_BROADCAST_ENTRY_THRESHOLD` under the stock host remains a separate admission-policy question.

Therefore the optional threshold-48 policy must not be applied merely to “preserve” BTT64.

## Linked-image evidence

The multicast32 build contract expects:

```text
                                  stock        P009      delta
.bss proper                       22,284      23,012      +728 B
.memory_manager_heap reservation 229,896     229,896         0 B
```

The +728 B `.bss` delta is expected to be:

```text
rx_buffer_vcom                           128 -> 512 B   (+384)
sli_zigbee_broadcast_table_data          240 -> 512 B   (+272)
sli_zigbee_incoming_aps_frame_counters     8 ->  52 B   (+44)
sli_zigbee_multicast_table               104 -> 128 B   (+24)
alignment/layout                                          (+4)
```

CI verifies those exact section and symbol sizes against the freshly linked ELF. A mismatch fails the artifact; no Home Assistant-side measurement is required to accept this compile-time resource change.

For this exact stack generation the broadcast backing array is **8 B per entry** and multicast membership storage is **4 B per entry**. Use actual linker/symbol evidence rather than generic per-entry estimates.

The unchanged 229,896-B `.memory_manager_heap` region is a **reservation**, not a measurement of free Zigbee packet memory after startup. Runtime pool acquisition, fragmentation and low-water marks are separate questions.

Other measured retained arrays include:

```text
retry queue                         320 B
source-route table data           1,016 B
route table                       2,040 B
child table                       1,560 B
APS duplicate rejection            256 B
```

## Why multicast32 is included without an occupancy campaign

The multicast table controls coordinator memberships used to receive group traffic; it is not a multicast transmit queue. Pinned herdsman consumes fixed memberships and dynamically registers application groups. With roughly 21 application groups, 26 entries leaves limited theoretical margin.

Raising 26 -> 32:

- costs only 24 B of raw linked `.bss` on this build;
- does not change routing, broadcast admission, channel, PAN, keys, transport, or transmit pacing;
- cannot exceed a protocol-visible network identity limit;
- provides six useful membership slots.

That risk/benefit is favorable enough to include directly rather than spending time collecting occupancy evidence first.

## Transport contract

```text
EUSART1
115200 baud
no hardware flow control
P009 RX buffer 512 B
stock rollback RX buffer 128 B
```

At 115200 8N1, 512 B is roughly 44 ms of nominal line-rate burst storage versus ~11 ms at 128 B. It does not raise sustained throughput.

Do not copy ZBT-2-specific 460800/CTS-RTS settings onto the SONOFF board without proof that the ESP bridge, pins and firmware support them end to end.

## Verification contract

The CI bundle treats these as separate evidence layers:

1. patched/stock source-profile inputs;
2. generated component/configuration output and linker maps;
3. linked ELF section/symbol assertions;
4. hashed GBL/HEX/OUT artifacts;
5. post-startup runtime evidence collected later by the single Zigbee2MQTT owner.

A source file is not labelled “effective configuration”, and a GBL hash acknowledgment is not device-side attestation.
