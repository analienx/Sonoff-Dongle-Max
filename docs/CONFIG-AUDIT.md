# P009 effective configuration audit overlay

This is a **separate diagnostic artifact**, not part of the first firmware-only P009 deployment.

It patches pinned zigbee-herdsman 10.9.1 only to read, after normal stock initialization:

- `BROADCAST_TABLE_SIZE`
- `NEW_BROADCAST_ENTRY_THRESHOLD`
- `KEY_TABLE_SIZE`
- `MAX_END_DEVICE_CHILDREN`
- `RETRY_QUEUE_SIZE`
- `SUPPORTED_NETWORKS`
- `MTORR_FLOW_CONTROL`
- `SEND_MULTICASTS_TO_SLEEPY_ADDRESS`

Each result is logged as `[P009 CONFIG] ... actual=... readStatus=...` using the existing owner connection. It does not set those values, clear counters, retry sends, change routing, or open a second NCP transport.

Purpose: close the super-executor review's effective-runtime configuration gap without making speculative production changes. Use only when the supervisor explicitly requests runtime audit evidence.
