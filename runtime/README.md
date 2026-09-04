# Optional P009 zigbee-herdsman 10.9.1 runtime overlay

Prepared only as a second-stage option after firmware-only P009 testing.

Pinned source: zigbee-herdsman 10.9.1 commit `0968f979d558874b17396c96b66382d4236bbdcd`.

The overlay sets and immediately reads back:

```text
BROADCAST_TABLE_SIZE               64
NEW_BROADCAST_ENTRY_THRESHOLD      48
RETRY_QUEUE_SIZE                   16
MTORR_FLOW_CONTROL                  1
SUPPORTED_NETWORKS                  1
SEND_MULTICASTS_TO_SLEEPY_ADDRESS  0
```

Threshold 48 reserves 16 of 64 broadcast-table entries for relaying broadcasts originated elsewhere. Retry queue remains 16. No P007-style BUSY retry loops are added.

Each value emits a `[P009 EZSP]` marker and startup fails on set/readback mismatch.

Do not modify the official Zigbee2MQTT add-on container in place. If this overlay is authorized, package it into a separate pinned custom add-on/image.
