# P009 MG24 resource profile

Target: SONOFF Dongle-M / Dongle Max, `EFR32MG24A420F1536IM48`.

Pinned builder: `Nerivec/silabs-firmware-builder@858c34b0eb6f53a2e0c89455ea489ceaa62d58db`

Pinned stack/toolchain: Simplicity SDK 2026.6.1, EmberZNet 9.1.1, EZSP 19, GCC 14.2.1.

P009 changes exactly two compile-time values:

```text
SL_ZIGBEE_BROADCAST_TABLE_SIZE  30 -> 64
SL_ZIGBEE_KEY_TABLE_SIZE         1 -> 12
```

Retained MG24 large-network profile:

```text
SL_ZIGBEE_ROUTE_TABLE_SIZE                     254
SL_ZIGBEE_SOURCE_ROUTE_TABLE_SIZE              254
SL_ZIGBEE_ADDRESS_TABLE_SIZE                   128
SL_ZIGBEE_APS_UNICAST_MESSAGE_COUNT            128
SL_ZIGBEE_DISCOVERY_TABLE_SIZE                  16
SL_ZIGBEE_MULTICAST_TABLE_SIZE                 26
SL_ZIGBEE_NEIGHBOR_TABLE_SIZE                  26
SL_ZIGBEE_BINDING_TABLE_SIZE                   32
SL_ZIGBEE_MAX_END_DEVICE_CHILDREN              64
SL_ZIGBEE_APS_DUPLICATE_REJECTION_MAX_ENTRIES 64
SL_ZIGBEE_PACKET_BUFFER_HEAP_SIZE              HUGE
retry queue                                     16
store-and-forward                                5
```

Transport invariants: EUSART1, 115200 baud, no flow control. Do not change NVM/network identity.

Optional host-side runtime policy is documented under `runtime/README.md`; firmware-only P009 with stock Z2M is tested first.
