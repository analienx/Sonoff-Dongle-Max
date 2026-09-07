# P010 diagnostic-only BUSY pressure overlay

This overlay is **not a tuning profile**. It exists only to identify which Ember/NCP resource is under pressure if the firmware-only P009 test still produces a real `BUSY` send failure.

Pinned zigbee-herdsman 10.9.1 commit:

```text
0968f979d558874b17396c96b66382d4236bbdcd
```

## Trigger paths

Only `SLStatus.BUSY` returned from:

- ZCL group / multicast;
- ZCL broadcast;
- ZDO broadcast.

## Timing contract

The original BUSY path **does not await diagnostics**. It schedules a read-only snapshot and immediately throws the same original send error.

The snapshot:

- is queued through the adapter owner rather than opening a second NCP client;
- uses `ezspReadCounters()` only;
- is single-flight;
- coalesces repeated triggers for five seconds;
- logs its own read latency;
- never retries the failed send;
- never clears counters;
- never changes routing, configuration or queue sizes.

This matters because the older P010 draft awaited `ezspReadCounters()` before propagating BUSY, which changed the timing of the failure being diagnosed.

## Evidence

Logs are emitted under `[P010 PRESSURE]` with one of:

```text
snapshot=ok
snapshot=failed
snapshot=queue-failed
snapshot=coalesced
```

A successful snapshot includes:

```text
ASH_OVERFLOW_ERROR
ASH_FRAMING_ERROR
ASH_OVERRUN_ERROR
ALLOCATE_PACKET_BUFFER_FAILURE
PHY_TO_MAC_QUEUE_LIMIT_REACHED
NWK_RETRY_OVERFLOW
PHY_CCA_FAIL_COUNT
BROADCAST_TABLE_FULL
ADDRESS_CONFLICT_SENT
```

Interpret these counters against the last known hourly `ezspReadAndClearCounters()` boundary or NCP reset. A zero delta does **not** by itself prove that the broadcast-table local-admission threshold was not responsible for a BUSY.

## Deployment boundary

Do not deploy P010 during the first P009 firmware-only acceptance. Use it only after a residual BUSY when the supervisor specifically wants event-adjacent counter evidence.

The P010 artifact remains separate from the optional P009 EZSP policy overlay so diagnostics and tuning cannot be confused.
